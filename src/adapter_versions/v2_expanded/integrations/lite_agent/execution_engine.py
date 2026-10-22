"""Extracted LiteAgent support module; keep application semantics generic."""

from __future__ import annotations
import copy
import json
import re
import time
from typing import Any
import jsonschema
from . import (
    batch_table_semantics,
    calc_semantics,
    completion_recovery,
    impress_cover_semantics,
    impress_semantics,
    impress_table_row,
    spreadsheet_open_semantics,
    verified_artifact_handoff,
    table_ratio_compute,
    pdf_table_selection,
)
from .adapter_results import (
    adapter_context_hint as adapter_context_hint,
    billing_reconciliation_argument_errors,
    compact_adapter_body as compact_adapter_body,
    utc_now,
)
from .completion_policy import (
    action_is_read_only as is_read_only,
    canonical_action_request,
    command_is_read_only,
    effective_canonical_action,
    completion_claim_contradictions as completion_claim_contradictions,
    completion_response_contract_errors,
)
from .clipboard_path_semantics import (
    argument_contract_errors as clipboard_path_argument_contract_errors,
)
from .gui_policy import repeated_gui_action_error
from .gui_actions import GUI_REQUEST_SCHEMA, build_gui_command, map_gui_coordinates
from .impress_background import background_argument_contract_errors
from .impress_page_number import page_number_argument_contract_errors
from .impress_role_formatting import (
    multislide_role_argument_contract_errors,
    multislide_visual_title_argument_contract_errors,
)
from .impress_role_text_update import role_text_update_argument_contract_errors
from .impress_title_formatting import title_format_argument_contract_errors
from .impress_image_insertion import image_insertion_argument_contract_errors
from .impress_personal_information import personal_information_argument_contract_errors
from .impress_textboxes import textbox_color_argument_contract_errors
from .instruction_semantics import (
    content_formatting_argument_contract_errors,
    messages_query_argument_contract_errors,
    strict_instruction_required_actions,
)
from .semantic_requirements import strict_semantic_action_equivalents
from .standard_location_semantics import (
    argument_contract_errors as standard_location_argument_contract_errors,
)
from .workspace_open_semantics import (
    argument_contract_errors as workspace_open_argument_contract_errors,
)
from .generic_routing import (
    discovered_adapter_routes,
    recovery_blocked_actions,
)
from .recovery_surface import last_failure_summary
from .request_blocks import request_block_is_stale, is_tools_search_provenance_error
from .context_projection import safe_action
from .safety import sanitize_agent_visible_result, sanitize_gui_result_for_model
from .tool_catalog import (
    DIRECT_ACTION_SCHEMAS,
    FORBIDDEN_DATASET_ACTIONS,
    action_from_tool_name,
    build_tools,
    search_actions,
    tool_name,
)
from .tool_validation import validate_model_visible_tool_arguments
from .runtime_policy import (
    ACTION_BLOCK_WINDOW_STEPS,
    RepeatedRequestBlocked,
    argument_signature,
    error_signature,
)
from .state_model import ExecutionEvent, RuntimeState
from .state_core import normalize_organization_path
from .filesystem_contexts import (
    ORGANIZATION_SKIP_ACTION,
    ORGANIZATION_SKIP_TOOL_NAME,
    organization_skip_tool,
)
from .organization_validation import VERIFY_ACTION, VERIFY_TOOL, check_classification, current_review_tool, directory_inspection_requested


def _strict_search_semantic_actions(state: RuntimeState) -> list[str]:
    """Include declared public alternatives when disambiguating catalog results."""
    required = strict_instruction_required_actions(state.domain, state.instruction)
    equivalents = strict_semantic_action_equivalents(state)
    return list(
        dict.fromkeys(
            [
                candidate
                for action in required
                for candidate in (action, *sorted(equivalents.get(action, set())))
            ]
        )
    )


def _is_read_only_adapter_event(event: Any, default_domain: str) -> bool:
    """Classify a prior adapter event without treating read-only commands as writes."""
    _domain, action, arguments = effective_canonical_action(event, default_domain)
    return is_read_only(action) or command_is_read_only(action, arguments)


def _organization_route_lease(
    state: RuntimeState, route: tuple[Any, Any], arguments: dict[str, Any] | None = None
) -> bool:
    """Allow only the phase-specific routes synthesized by the file workflow."""
    if not state.filesystem_move_requested():
        return False
    observation = state.filesystem_observation_state()
    if not isinstance(observation, dict) or observation.get("complete") is not True:
        return False
    current = state.filesystem_organization_current_entry()
    pending_paths = set(state.filesystem_organization_pending_entries())
    if route == ("os", "filesystem.find"):
        return directory_inspection_requested(state, arguments or {})
    if route == ("os", "filesystem.rename"):
        if current is None:
            return False
        check = state.filesystem_organization_check(current)
        return bool(check and check.get("disposition") == "move")
    # A model may choose an owning reader that is semantically equivalent for
    # the current object (for example the text reader for a document).  The
    # important protocol invariant is one exact current source and successful
    # content evidence before the move, not a PDF-only route name.
    if route not in {
        ("os", "pdf.extract_text_batch"),
        ("os", "image.extract_text_batch"),
        ("os", "desktop.open_path"),
        ("vs_code", "file.read_text"),
        ("libreoffice_writer", "document.read_file"),
        ("libreoffice_calc", "workbook.read_file"),
    }:
        return False
    params = (
        (arguments or {}).get("payload", {}).get("params", {})
        if isinstance((arguments or {}).get("payload"), dict)
        else {}
    )
    requested = None
    if isinstance(params, dict):
        requested = params.get("input_path") or params.get("path") or params.get("file_path")
        if requested is None:
            pattern = params.get("input_pattern")
            if isinstance(pattern, str) and not any(char in pattern for char in "*?[]"):
                requested = pattern
    requested_path = normalize_organization_path(requested)
    current = state.filesystem_organization_current_entry()
    current_path = normalize_organization_path(current.get("path")) if current else None
    if requested_path not in pending_paths or requested_path != current_path:
        return False
    active_path = normalize_organization_path(
        getattr(state, "filesystem_organization_active_path", None)
    )
    if active_path is None:
        # Lock the first explicitly selected pending object for this turn.
        state.filesystem_organization_active_path = requested_path
        return True
    return requested_path == active_path


def _validate_organization_skip(
    state: RuntimeState, arguments: dict[str, Any]
) -> None:
    """Validate a runner-only retain transition against the current object."""
    if not state.filesystem_move_requested():
        raise ValueError("organization.skip_current requires a filesystem organization task")
    observation = state.filesystem_observation_state()
    if not isinstance(observation, dict) or observation.get("complete") is not True:
        raise ValueError("filesystem observation must complete before skipping an object")
    current = state.filesystem_organization_current_entry()
    if current is None:
        raise ValueError("there is no unresolved organization object to skip")
    path = arguments.get("path")
    reason = arguments.get("reason")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("organization.skip_current requires one exact path")
    if any(char in path for char in "*?[]"):
        raise ValueError("organization.skip_current requires an exact path, not a glob")
    if normalize_organization_path(path) != normalize_organization_path(current.get("path")):
        raise ValueError("organization.skip_current path must match the current object")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("organization.skip_current requires a factual reason")
    check = state.filesystem_organization_check(current)
    if not check or check.get("disposition") != "retain" or check.get("destination_directory") != str(path).rsplit("/", 1)[0]:
        raise ValueError("organization.skip_current requires a passed independent classification and current-location compliance check")


def _model_visible_recovery_blocks(
    blocks: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project block state without exposing internal request/error signatures.

    Signatures are useful for duplicate detection inside the Runner, but they
    are opaque implementation details and have no value for model planning.
    Keep only bounded status fields and a generic reason in the model-facing
    search result; the complete block remains in the immutable event ledger.
    """
    visible: list[dict[str, Any]] = []
    for block in blocks.values():
        if not isinstance(block, dict):
            continue
        scope = block.get("block_scope")
        item: dict[str, Any] = {
            "action": safe_action(block.get("action")),
            "block_scope": scope if scope in {"window", "episode"} else "window",
            "request_scope": "exact_normalized_arguments",
            "fallback_reason": (
                "only the original argument combination is blocked; "
                "the same parameterized action remains available with corrected arguments"
            ),
        }
        for key in ("blocked_at_step", "blocked_until_step"):
            value = block.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                item[key] = value
        visible.append(item)
    return visible


class ExecutionEngineMixin:
    @staticmethod
    def _validate_adapter_arguments(
        domain: str,
        action: str,
        arguments: dict[str, Any],
        *,
        strict_generic: bool = False,
    ) -> None:
        direct_schema = DIRECT_ACTION_SCHEMAS.get(domain, {}).get(action)
        if direct_schema is not None:
            schema = {
                "type": "object",
                "properties": direct_schema["properties"],
                "required": direct_schema["required"],
                "additionalProperties": False,
            }
            for keyword in ("allOf", "anyOf", "oneOf"):
                if keyword in direct_schema:
                    schema[keyword] = direct_schema[keyword]
            if strict_generic:
                strict_tool = next(
                    (
                        tool
                        for tool in build_tools(
                            domain,
                            [action],
                            include_gui=False,
                            include_control_tools=False,
                            strict_generic=True,
                        )
                        if tool["function"]["name"] == tool_name(action)
                    )
                )
                schema = strict_tool["function"]["parameters"]
            jsonschema.validate(arguments, schema)
            return
        for key in ("params", "target", "document"):
            if key in arguments and (not isinstance(arguments[key], dict)):
                raise ValueError(
                    f"{key} must be an object, got {type(arguments[key]).__name__}"
                )
        if "verify" in arguments and (
            not isinstance(arguments["verify"], list)
            or any((not isinstance(item, dict) for item in arguments["verify"]))
        ):
            raise ValueError("verify must be an array of objects")
        if "timeout_ms" in arguments and (
            isinstance(arguments["timeout_ms"], bool)
            or not isinstance(arguments["timeout_ms"], int)
            or (not 100 <= arguments["timeout_ms"] <= 120000)
        ):
            raise ValueError("timeout_ms must be an integer between 100 and 120000")

    @staticmethod
    def _gui_command(arguments: dict[str, Any]) -> str:
        return build_gui_command(arguments)

    def _execute_holo_gui_request(
        self,
        arguments: dict[str, Any],
        screenshot: bytes | None,
    ) -> dict[str, Any]:
        """Run one planner GUI delegation through the configured Holo boundary."""
        if screenshot is None:
            raise ValueError(
                "gui_request requires the latest screenshot for Holo grounding"
            )
        if not isinstance(screenshot, (bytes, bytearray, memoryview)) or not screenshot:
            raise ValueError("gui_request requires non-empty screenshot bytes")
        gateway = getattr(self, "holo_gui_gateway", None)
        if gateway is not None:
            result = gateway(arguments, bytes(screenshot))
        else:
            grounder = getattr(self, "holo_grounder", None)
            executor = getattr(self, "gui_executor", None)
            if grounder is None:
                raise RuntimeError("Holo GUI delegation is not configured")
            if executor is None:
                raise RuntimeError("GUI executor is not configured")
            # Import lazily so the legacy direct-GUI path does not load Holo's
            # optional visual client or image decoder.
            from integrations.holo_agent.gateway import HoloGuiGateway

            result = HoloGuiGateway(grounder, executor).execute(
                arguments, bytes(screenshot)
            )
        if not isinstance(result, dict):
            raise ValueError("Holo GUI gateway must return an object")
        return result

    @staticmethod
    def _holo_audit_arguments(result: dict[str, Any]) -> dict[str, Any] | None:
        """Extract the bounded coordinate-bearing action for the audit ledger."""
        nested = result.get("result")
        if isinstance(nested, dict) and isinstance(nested.get("grounded_action"), dict):
            return copy.deepcopy(nested["grounded_action"])
        prepared = result.get("prepared_action")
        if isinstance(prepared, dict):
            model_arguments = prepared.get("model_arguments")
            name = prepared.get("name")
            if isinstance(model_arguments, dict) and isinstance(name, str):
                return {"action": name, **copy.deepcopy(model_arguments)}
        grounding = result.get("grounding")
        if isinstance(grounding, dict):
            name = grounding.get("name")
            model_arguments = grounding.get("arguments")
            if isinstance(name, str) and isinstance(model_arguments, dict):
                return {"action": name, **copy.deepcopy(model_arguments)}
        return None

    def execute_proposal(
        self,
        state: RuntimeState,
        proposal: dict[str, Any],
        screenshot_before: str | None = None,
        screenshot: bytes | None = None,
    ) -> ExecutionEvent:
        if state.done or state.failed:
            raise ValueError("episode is terminal; no further tool may execute")
        started = time.monotonic()
        model_visible_tools = proposal.get("_model_visible_tools")
        recorded_proposal = {
            key: value
            for key, value in proposal.items()
            if key not in {"_model_visible_tools", "_gui_coordinate_frame"}
        }
        if model_visible_tools is not None:
            recorded_proposal["model_visible_schema_enforced"] = True
        event = ExecutionEvent(
            step=len(state.events) + 1,
            timestamp_utc=utc_now(),
            proposed=recorded_proposal,
            screenshot_before=screenshot_before,
        )
        tool = proposal.get("tool")
        repair_confirmed = False
        organization_skip_handled = False
        organization_check_handled = False
        if tool == "propose_done":
            event.proposed["kind"] = "completion"
        try:
            arguments = json.loads(proposal.get("arguments_raw") or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must decode to an object")
            model_arguments = copy.deepcopy(arguments)
            event.parsed = True
            event.proposed["arguments"] = arguments
            if tool in {table_ratio_compute.TOOL_NAME, pdf_table_selection.TOOL_NAME}:
                action = None
            elif tool == "repair_confirm":
                raise ValueError("repair_confirm is retired; submit corrected model-owned arguments through the original public API")
            else:
                action = action_from_tool_name(state.domain, str(tool))
            if tool == VERIFY_TOOL:
                current = state.filesystem_organization_current_entry()
                if current is None:
                    raise ValueError("there is no current source object to verify")
                expected = current_review_tool(state, current)
                validate_model_visible_tool_arguments([expected], VERIFY_TOOL, arguments)
                if model_visible_tools is not None:
                    validate_model_visible_tool_arguments(model_visible_tools, VERIFY_TOOL, arguments)
                event.proposed.update({"kind": "organization", "action": VERIFY_ACTION})
                event.validated = True
                event.result = check_classification(self, state, arguments, screenshot or self._latest_screenshot)
                event.proposed["checker_diagnostics"] = event.result.pop("_checker_diagnostics", [])
                event.executed = True
                organization_check_handled = True
            if tool == ORGANIZATION_SKIP_TOOL_NAME:
                jsonschema.validate(
                    arguments,
                    organization_skip_tool()["function"]["parameters"],
                )
                if model_visible_tools is not None:
                    if not isinstance(model_visible_tools, list):
                        raise ValueError("captured model-visible tools must be an array")
                    validate_model_visible_tool_arguments(
                        model_visible_tools, str(tool), arguments
                    )
                _validate_organization_skip(state, arguments)
                event.proposed.update(
                    {"kind": "organization", "action": ORGANIZATION_SKIP_ACTION}
                )
                event.validated = True
                event.executed = True
                event.result = {
                    "status": "ok",
                    "executed": True,
                    "path": normalize_organization_path(arguments["path"]),
                    "disposition": "skipped",
                    "reason": arguments["reason"],
                }
                state.filesystem_organization_active_path = None
                organization_skip_handled = True
            if tool in {table_ratio_compute.TOOL_NAME, pdf_table_selection.TOOL_NAME}:
                computation = pdf_table_selection if tool == pdf_table_selection.TOOL_NAME else table_ratio_compute
                expected = computation.tool(state)
                jsonschema.validate(arguments, expected["function"]["parameters"])
                if model_visible_tools is not None:
                    validate_model_visible_tool_arguments(
                        model_visible_tools, str(tool), arguments
                    )
                event.proposed.update(
                    {"kind": "computation", "action": computation.ACTION}
                )
                event.validated = True
                event.result = computation.compute(state, arguments)
                event.executed = True
            if action:
                if action in FORBIDDEN_DATASET_ACTIONS:
                    raise ValueError(
                        f"task-specific Adapter action is disabled in strict mode: {action}"
                    )
                event.proposed.update({"kind": "adapter", "action": action})
                if model_visible_tools is not None and not repair_confirmed:
                    if not isinstance(model_visible_tools, list):
                        raise ValueError(
                            "captured model-visible tools must be an array"
                        )
                    validate_model_visible_tool_arguments(
                        model_visible_tools, str(tool), arguments
                    )
                elif action not in set(self.selected_actions(state)):
                    raise ValueError(
                        f"action is not in current Top-K exposure: {action}"
                    )
                structured_impress_step = impress_semantics.next_picture_height_action(
                    state
                )
                if (
                    not repair_confirmed
                    and state.domain == "libreoffice_impress"
                    and structured_impress_step is not None
                    and structured_impress_step["action"] == "shape.set_geometry"
                ):
                    if action != structured_impress_step["action"]:
                        raise ValueError(
                            "Impress picture-height mutation must use the pending "
                            f"observation-derived action: {structured_impress_step!r}"
                        )
                    if arguments:
                        raise ValueError(
                            "Impress picture-height mutation arguments are injected by "
                            "the Runner; call the constrained tool with no arguments"
                        )
                    arguments = copy.deepcopy(structured_impress_step["arguments"])
                    event.proposed["model_arguments"] = model_arguments
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = copy.deepcopy(arguments)
                    if not impress_semantics.validate_arguments(
                        state, action, arguments
                    ):
                        raise ValueError(
                            "injected Impress picture-height arguments did not match "
                            "the pending semantic plan"
                        )
                # The post-execution filesystem bookkeeping below also inspects
                # this value for direct adapter actions; keep it defined outside
                # the multi-app-only route validation branch.
                route = None
                if action == "adapter.call" and state.domain == "multi_apps":
                    route = (arguments.get("adapter"), arguments.get("action"))
                    if pdf_table_selection.active(state):
                        if route not in pdf_table_selection.allowed_routes(state):
                            raise ValueError(f"route prerequisites are not satisfied for {route!r}; eligible_routes={sorted(pdf_table_selection.allowed_routes(state))!r}. {pdf_table_selection.stage_hint(state)} No mutation executed.")
                        if route not in discovered_adapter_routes(state):
                            raise ValueError(f"multi_apps.adapter.call requires a matching public tools_search result before execution; required_search={route[0]}.{route[1]}; no mutation executed")
                        if route == ("libreoffice_calc", "range.format"):
                            errors = pdf_table_selection.format_errors(state, arguments.get("payload", {}).get("params", {}))
                            if errors:
                                raise ValueError("; ".join(errors))
                    derived_post_mutation_route = (
                        batch_table_semantics.next_post_mutation_route(state)
                    )
                    native_consumer_route = (
                        arguments.get("adapter") == "libreoffice_calc"
                        and arguments.get("action")
                        in {
                            "range.read",
                            "range.write",
                            "spreadsheet.read_file",
                            "spreadsheet.write_range",
                            "workbook.read_file",
                        }
                        and batch_table_semantics.native_pdf_table_observation_complete(
                            state
                        )
                        and batch_table_semantics._valid_target_inspection(state)
                        is not None
                        and batch_table_semantics.observed_created_table(state) is None
                        and not batch_table_semantics.inspection_pending(state)
                    )
                    organization_route_lease = _organization_route_lease(
                        state, route, arguments
                    )
                    if (
                        route is not None
                        and state.requested_mail_recipient_target()
                        and state.source_read_handoff_pending()
                        and not state._is_mail_recipient_route(*route)
                    ):
                        raise ValueError(
                            "mail recipient target is still awaiting a public "
                            "tools_search result for "
                            "thunderbird.compose.set_recipients or "
                            "mail.compose_recipients"
                        )
                    organization_reader_route = route in {
                        ("os", "pdf.extract_text_batch"),
                        ("os", "image.extract_text_batch"),
                        ("os", "desktop.open_path"),
                        ("vs_code", "file.read_text"),
                        ("libreoffice_writer", "document.read_file"),
                        ("libreoffice_calc", "workbook.read_file"),
                    }
                    if (
                        (
                            state.filesystem_move_requested()
                            and route
                            in {
                                ("os", "pdf.extract_text_batch"),
                                ("os", "filesystem.rename"),
                            }
                            and not organization_route_lease
                            and not organization_reader_route
                        )
                        or (
                            route not in discovered_adapter_routes(state)
                            and route != derived_post_mutation_route
                            and not native_consumer_route
                            and not organization_route_lease
                            and not (
                                state.filesystem_move_requested()
                                and (organization_reader_route or route == ("os", "filesystem.rename"))
                            )
                        )
                    ):
                        raise ValueError(
                            "multi_apps.adapter.call requires a matching public "
                            "tools_search result before execution"
                        )
                merged_text_step = state.next_merged_text_action()
                sheet_lifecycle_step = state.next_sheet_copy_lifecycle_action()
                annual_change_step = state.next_annual_percentage_change_action()
                monthly_totals_step = state.next_monthly_column_totals_action()
                scaled_display_step = state.next_scaled_number_display_action()
                labeled_concatenation_step = state.next_labeled_concatenation_action()
                period_rate_step = state.next_period_rate_action()
                stacked_pivot_step = state.next_stacked_percentage_pivot_action()
                all_slide_background_arguments = state.all_slide_background_arguments()
                title_edge_step = state.next_title_edge_position_action()
                title_update_step = state.next_slide_title_update_action()
                title_format_step = state.next_slide_title_format_action()
                sized_image_step = None
                picture_heights_step = state.next_picture_heights_by_slide_action()
                table_row_step = None
                named_table_step = state.next_named_slide_table_action()
                image_edge_step = state.next_image_edge_position_action()
                table_edge_step = state.next_table_edge_position_action()
                personal_cleanup_step = None
                role_text_step = state.next_slide_role_text_format_action()
                content_format_step = state.next_slide_content_format_action()
                calc_summary_step = (
                    annual_change_step
                    or monthly_totals_step
                    or scaled_display_step
                    or labeled_concatenation_step
                    or period_rate_step
                )
                merged_text_step = None
                sheet_lifecycle_step = None
                annual_change_step = None
                monthly_totals_step = None
                scaled_display_step = None
                labeled_concatenation_step = None
                period_rate_step = None
                stacked_pivot_step = None
                all_slide_background_arguments = None
                title_edge_step = None
                title_update_step = None
                title_format_step = None
                sized_image_step = None
                picture_heights_step = None
                table_row_step = None
                named_table_step = None
                image_edge_step = None
                table_edge_step = None
                personal_cleanup_step = state.next_title_range_personal_info_cleanup_action()
                role_text_step = None
                content_format_step = None
                calc_summary_step = None
                if (
                    calc_summary_step is not None
                    and calc_summary_step["action"] == action
                ):
                    arguments = copy.deepcopy(calc_summary_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_source_table_observation"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    action == "slide.set_background"
                    and all_slide_background_arguments is not None
                    and (not state.successful_action_events("slide.set_background"))
                ):
                    arguments = copy.deepcopy(all_slide_background_arguments)
                    event.proposed["arguments_source"] = "instruction_derived_scope"
                    event.proposed["arguments"] = arguments
                if title_edge_step is not None and action == title_edge_step["action"]:
                    arguments = copy.deepcopy(title_edge_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    title_update_step is not None
                    and action == title_update_step["action"]
                ):
                    arguments = copy.deepcopy(title_update_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    title_format_step is not None
                    and action == title_format_step["action"]
                ):
                    arguments = copy.deepcopy(title_format_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    sized_image_step is not None
                    and action == sized_image_step["action"]
                ):
                    arguments = copy.deepcopy(sized_image_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    picture_heights_step is not None
                    and action == picture_heights_step["action"]
                ):
                    arguments = copy.deepcopy(picture_heights_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if table_row_step is not None and action == table_row_step["action"]:
                    arguments = copy.deepcopy(table_row_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    named_table_step is not None
                    and action == named_table_step["action"]
                ):
                    arguments = copy.deepcopy(named_table_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if image_edge_step is not None and action == image_edge_step["action"]:
                    arguments = copy.deepcopy(image_edge_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if table_edge_step is not None and action == table_edge_step["action"]:
                    arguments = copy.deepcopy(table_edge_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    personal_cleanup_step is not None
                    and action == personal_cleanup_step["action"]
                    and action != "presentation.inspect"
                ):
                    arguments = copy.deepcopy(personal_cleanup_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if role_text_step is not None and action == role_text_step["action"]:
                    arguments = copy.deepcopy(role_text_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    content_format_step is not None
                    and action == content_format_step["action"]
                ):
                    arguments = copy.deepcopy(content_format_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_presentation_observation"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    sheet_lifecycle_step is not None
                    and sheet_lifecycle_step["action"] == action
                    and (action in {"sheet.rename", "sheet.copy"})
                ):
                    arguments = copy.deepcopy(sheet_lifecycle_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_workbook_observation"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    merged_text_step is not None
                    and merged_text_step["action"] == action
                    and (action in {"range.merge", "range.write", "range.format"})
                ):
                    arguments = copy.deepcopy(merged_text_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_derived_state_step"
                    )
                    event.proposed["arguments"] = arguments
                if (
                    action == "pivot.create"
                    and stacked_pivot_step is not None
                    and (stacked_pivot_step["action"] == action)
                ):
                    arguments = copy.deepcopy(stacked_pivot_step["arguments"])
                    event.proposed["arguments_source"] = (
                        "instruction_and_source_table_observation"
                    )
                    event.proposed["arguments"] = arguments
                self._validate_adapter_arguments(
                    state.domain, action, arguments, strict_generic=True
                )
                semantic_argument_errors = background_argument_contract_errors(
                    state, action, arguments
                )
                if action == "adapter.call" and state.domain == "multi_apps":
                    route = (arguments.get("adapter"), arguments.get("action"))
                    params = ((arguments.get("payload") or {}).get("params") or {})
                    organization_intent = state.filesystem_move_requested()
                    if (
                        route == ("os", "filesystem.find")
                        and organization_intent
                        and params.get("kind", "file") != "any"
                    ):
                        semantic_argument_errors.append(
                            "filesystem.find must use kind=any for a filesystem organization "
                            "or classification task so directories are not omitted; retry "
                            "the same discovery with kind=any before moving any object"
                        )
                    observation = state.filesystem_observation_state()
                    if (
                        route == ("os", "filesystem.find")
                        and organization_intent
                        and not (isinstance(observation, dict) and observation.get("complete") is True)
                        and (params.get("name_patterns") != ["*"] or params.get("recursive", False) is not False)
                    ):
                        semantic_argument_errors.append(
                            "Initial organization inventory must use name_patterns=['*'] "
                            "and recursive=false to include every direct source entry "
                            "and comparison reference. Select the source directory in "
                            "roots; inspect a nested directory separately when it becomes "
                            "the current object."
                        )
                    if (
                        route == ("os", "filesystem.find")
                        and isinstance(observation, dict)
                        and observation.get("complete") is True
                        and not directory_inspection_requested(state, arguments)
                    ):
                        semantic_argument_errors.append(
                            "filesystem observation is complete; classify the exact "
                            "observed entries and call filesystem.rename with exact source "
                            "and destination paths (the destination parent is created by "
                            "rename when absent), or read content only for an ambiguous "
                            "file; for a current source directory, inspect only its exact root "
                            "with kind=any, name_patterns=['*'], recursive=true, max_depth=1..4, "
                            "max_results=1..200. Do not rediscover the source inventory."
                        )
                    if route == ("os", "filesystem.rename"):
                        rename_params = params if isinstance(params, dict) else {}
                        source = rename_params.get("source")
                        destination = rename_params.get("destination")
                        if not isinstance(source, str) or not isinstance(destination, str):
                            semantic_argument_errors.append(
                                "filesystem.rename moves exactly one object; source and "
                                "destination must each be one concrete path string"
                            )
                        elif any(char in source or char in destination for char in "*?[]"):
                            semantic_argument_errors.append(
                                "filesystem.rename requires exact source and destination "
                                "paths; globs and multi-file patterns are not allowed"
                            )
                        elif organization_intent and isinstance(observation, dict) and observation.get(
                            "complete"
                        ) is True:
                            pending_paths = set(state.filesystem_organization_pending_entries())
                            current = state.filesystem_organization_current_entry()
                            normalized_source = normalize_organization_path(source)
                            check = state.filesystem_organization_check(current)
                            if normalized_source not in pending_paths or (
                                current is not None
                                and normalized_source
                                != normalize_organization_path(current.get("path"))
                            ):
                                semantic_argument_errors.append(
                                    "filesystem.rename source must exactly match the current "
                                    "observed, not-yet-moved object"
                                )
                            elif normalized_source in state.filesystem_organization_destinations():
                                semantic_argument_errors.append(
                                    "destination category directories are protected and cannot be moved as source objects"
                                )
                            elif current and state.filesystem_organization_unverified_move(current):
                                semantic_argument_errors.append(
                                    "a previous move executed but physical verification failed; do not repeat the mutation or advance this object"
                                )
                            elif not check or check.get("disposition") != "move":
                                semantic_argument_errors.append(
                                    "filesystem.rename requires a passed independent classification check for this object"
                                )
                            elif normalize_organization_path(destination.rsplit("/", 1)[0]) != check.get("destination_directory"):
                                semantic_argument_errors.append(
                                    "filesystem.rename destination must match the independently verified category directory"
                                )
                            elif destination.rsplit("/", 1)[-1] != source.rsplit("/", 1)[-1]:
                                semantic_argument_errors.append(
                                    "filesystem.rename destination must preserve the exact "
                                    "source basename; move one observed file at a time"
                                )
                            elif normalize_organization_path(destination) == normalized_source:
                                semantic_argument_errors.append(
                                    "filesystem.rename destination must differ from source; "
                                    "use organization__skip_current to classify an object "
                                    "that should remain in place"
                                )
                    elif organization_intent and organization_reader_route:
                        current = state.filesystem_organization_current_entry()
                        read_params = params if isinstance(params, dict) else {}
                        requested = (
                            read_params.get("input_path")
                            or read_params.get("path")
                            or read_params.get("file_path")
                        )
                        if requested is None:
                            pattern = read_params.get("input_pattern")
                            if isinstance(pattern, str) and not any(char in pattern for char in "*?[]"):
                                requested = pattern
                            else:
                                semantic_argument_errors.append(
                                    "organization readers must process exactly one current object; "
                                "use its exact normalized absolute path, never a basename or wildcard"
                                )
                        if current is not None and requested is not None:
                            current_path = normalize_organization_path(current.get("path"))
                            if normalize_organization_path(requested) != current_path:
                                semantic_argument_errors.append(
                                    "content reader must target the exact normalized path of the current organization object"
                                )
                semantic_argument_errors.extend(
                    billing_reconciliation_argument_errors(state, action, arguments)
                )
                semantic_argument_errors.extend(
                    messages_query_argument_contract_errors(
                        state.instruction, state.domain, action, arguments
                    )
                )
                semantic_argument_errors.extend(
                    content_formatting_argument_contract_errors(
                        state.instruction, action, arguments
                    )
                )
                semantic_argument_errors.extend(
                    page_number_argument_contract_errors(state, action, arguments)
                )
                semantic_argument_errors.extend(
                    textbox_color_argument_contract_errors(state, action, arguments)
                )
                semantic_argument_errors.extend(
                    multislide_role_argument_contract_errors(state, action, arguments)
                )
                semantic_argument_errors.extend(
                    multislide_visual_title_argument_contract_errors(
                        state, action, arguments
                    )
                )
                semantic_argument_errors.extend(
                    role_text_update_argument_contract_errors(state, action, arguments)
                )
                semantic_argument_errors.extend(
                    title_format_argument_contract_errors(state, action, arguments)
                )
                semantic_argument_errors.extend(
                    image_insertion_argument_contract_errors(state, action, arguments)
                )
                semantic_argument_errors.extend(
                    personal_information_argument_contract_errors(
                        state, action, arguments
                    )
                )
                semantic_argument_errors.extend(
                    standard_location_argument_contract_errors(state, action, arguments)
                )
                semantic_argument_errors.extend(
                    clipboard_path_argument_contract_errors(state, action, arguments)
                )
                semantic_argument_errors.extend(
                    workspace_open_argument_contract_errors(state, action, arguments)
                )
                semantic_argument_errors.extend(
                    spreadsheet_open_semantics.argument_contract_errors(
                        state, action, arguments
                    )
                )
                semantic_argument_errors.extend(
                    batch_table_semantics.argument_contract_errors(
                        state, action, arguments
                    )
                )
                semantic_argument_errors.extend(
                    verified_artifact_handoff.argument_contract_errors(
                        state, action, arguments
                    )
                )
                semantic_argument_errors.extend(
                    impress_cover_semantics.argument_contract_errors(
                        state, action, arguments
                    )
                )
                semantic_argument_errors.extend(
                    impress_table_row.argument_contract_errors(state, action, arguments)
                )
                if action == "table.sort":
                    calc_semantics.validate_sort_arguments(state, action, arguments)
                if semantic_argument_errors:
                    raise ValueError("; ".join(semantic_argument_errors))
                if action == "media.extract_audio" and "profile" in arguments:
                    raise ValueError(
                        "dataset-specific media extraction profiles are disabled in strict mode"
                    )
                if (
                    arguments != model_arguments
                    or event.proposed.get("arguments_source") is not None
                ):
                    structured_impress_injection = bool(
                        event.proposed.get("arguments_source")
                        == "instruction_and_presentation_observation"
                        and structured_impress_step is not None
                        and action == structured_impress_step["action"]
                        and arguments == structured_impress_step["arguments"]
                        and model_arguments == {}
                    )
                    cleanup_injection = bool(
                        event.proposed.get("arguments_source")
                        == "instruction_and_presentation_observation"
                        and personal_cleanup_step is not None
                        and action == personal_cleanup_step["action"]
                        and action != "presentation.inspect"
                        and arguments == personal_cleanup_step["arguments"]
                    )
                    if (
                        not repair_confirmed
                        and not structured_impress_injection
                        and not cleanup_injection
                    ):
                        raise RuntimeError(
                            "strict generic-only execution cannot rewrite or inject model arguments"
                        )
                active_block = state.active_request_block(action, arguments)
                if active_block is not None:
                    event.validated = True
                    raise RepeatedRequestBlocked(
                        {
                            "type": "RepeatedActionBlocked",
                            "detail": "this action and normalized argument combination is blocked for the remainder of the episode after reaching the same structured error twice; change the arguments or choose another action",
                            "executed": False,
                            "previous_step": active_block["blocked_at_step"],
                            "previous_error": active_block.get("previous_error"),
                            "blocked_action": action,
                            "argument_signature": active_block["argument_signature"],
                            "error_signature": active_block["error_signature"],
                            "block_scope": active_block["block_scope"],
                            "fallback_reason": "same_action_same_arguments_same_error_twice",
                        }
                    )
                current_identity = canonical_action_request(
                    state.domain, action, arguments
                )
                duplicate = next(
                    (
                        previous
                        for previous in reversed(state.events)
                        if previous.executed
                        and previous.proposed.get("kind") == "adapter"
                        and effective_canonical_action(previous, state.domain)
                        == current_identity
                    ),
                    None,
                )
                mutation_after_duplicate = bool(
                    duplicate is not None
                    and any(
                        (
                            previous.step > duplicate.step
                            and previous.executed
                            and (
                                previous.proposed.get("kind") == "gui"
                                or (
                                    previous.proposed.get("kind") == "adapter"
                                    and (
                                        not _is_read_only_adapter_event(
                                            previous, state.domain
                                        )
                                    )
                                )
                            )
                            for previous in state.events
                        )
                    )
                )
                latest_result = state.events[-1].result if state.events else None
                observation_retry = bool(
                    current_identity[:2] == ("os", "desktop.open_path")
                    and state.filesystem_move_requested()
                    and isinstance(latest_result, dict)
                    and latest_result.get("evidence_sufficient") is False
                    and sum(
                        previous.executed
                        and effective_canonical_action(previous, state.domain)[:2] == ("os", "desktop.open_path")
                        and effective_canonical_action(previous, state.domain)[2].get("path") == current_identity[2].get("path")
                        for previous in state.events
                    ) < 3
                )
                if (
                    duplicate is not None
                    # Removing a shape shifts collection positions: the same
                    # selector can now identify another live object to delete.
                    and current_identity[:2] != ("libreoffice_impress", "shape.delete")
                    and not (
                        is_read_only(current_identity[1])
                        or command_is_read_only(
                            current_identity[1], current_identity[2]
                        )
                    )
                    and not mutation_after_duplicate
                    and not observation_retry
                    and not completion_recovery.outcome_retry_allowed(
                        state, current_identity[0], current_identity[1], current_identity[2], duplicate.step
                    )
                    and not spreadsheet_open_semantics.inspection_retry_required(
                        state, action, arguments
                    )
                ):
                    raise ValueError(
                        f"identical successful action already executed at step {duplicate.step}; inspect state or choose a different action"
                    )
                event.validated = True
                result = self.adapter_executor.execute(
                    state.domain,
                    action,
                    arguments,
                    {"task_id": state.task_id, "step": event.step},
                )
                event.executed = bool(result.get("executed"))
                if event.executed and isinstance(result.get("organization_inventory"), list) and not isinstance(state.filesystem_organization_inventory, list):
                    # This is an internal server-side ledger; it is deliberately
                    # not copied into event.result/model context.
                    state.filesystem_organization_inventory = copy.deepcopy(
                        result["organization_inventory"]
                    )
                if event.executed and route == ("os", "filesystem.rename"):
                    # A successful classification+move completes the active
                    # object and advances the per-object workflow.
                    state.filesystem_organization_active_path = None
                event.result = result.get("result") if event.executed else None
                event.error = result.get("error") if not event.executed else None
            elif tool == "completion_revise":
                from . import completion_review

                if not completion_review.review_ready(
                    state, self._generic_completion_gate(state)
                ):
                    raise ValueError("completion_revise requires active completion review")
                validate_model_visible_tool_arguments(
                    [completion_review.revision_tool()], tool, arguments
                )
                if model_visible_tools is not None:
                    validate_model_visible_tool_arguments(model_visible_tools, tool, arguments)
                event.validated = True
                event.executed = True
                event.proposed["kind"] = "completion_review"
                event.result = {
                    "phase": "correction",
                    "discrepancy": arguments,
                    "guidance": "Correct the observed mismatch using public tools, then save and read back the changed result before completion review.",
                }
            elif tool == "tools_search":
                event.validated = True
                active_blocks = state.active_request_blocks()
                excluded_actions = recovery_blocked_actions(state)
                excluded_routes = state.blocked_routes()
                failure_summary = last_failure_summary(state)
                # Feed retrieval only coarse failure fields. Including the
                # failed action itself would boost that same action's lexical
                # score and recreate the recovery attractor we are removing.
                previous_error = (
                    {
                        key: value
                        for key, value in failure_summary.items()
                        if key != "action"
                    }
                    if failure_summary
                    else None
                )
                search_limit = 5 if active_blocks else 6
                query = str(arguments["query"])
                explicit_catalog_route = bool(
                    re.search(
                        r"(?<![\w.])(?:[a-z_][\w]*\.)+[a-z_][\w]*(?![\w.])",
                        query.casefold(),
                    )
                )
                matches = search_actions(
                    state.domain,
                    query,
                    limit=search_limit,
                    instruction=state.instruction,
                    stage_actions=self.selected_actions(state),
                    semantic_actions=_strict_search_semantic_actions(state),
                    recent_error=json.dumps(
                        previous_error, ensure_ascii=False, default=str
                    ),
                    excluded_actions=excluded_actions,
                    excluded_routes=excluded_routes,
                    strict_generic=True,
                )
                # Batch PDF workflows have a state-derived observation lease:
                # while native table observations are still missing, a free
                # form Qwen search (for example "close the file manager" or
                # "set a cell") can otherwise rank the workbook consumer and
                # leave the model looping on an unrelated route.  Search
                # results must reflect the current observation-derived next
                # step, independent of the wording chosen by the model.
                if state.domain == "multi_apps":
                    if (
                        batch_table_semantics.structured_pdf_source_discovery_pending(
                            state
                        )
                    ):
                        matches = search_actions(
                            state.domain,
                            "filesystem.find",
                            limit=search_limit,
                            instruction=state.instruction,
                            stage_actions=self.selected_actions(state),
                            semantic_actions=_strict_search_semantic_actions(state),
                            recent_error=json.dumps(
                                previous_error, ensure_ascii=False, default=str
                            ),
                            excluded_actions=excluded_actions,
                            excluded_routes=excluded_routes,
                            strict_generic=True,
                        )
                        matches = [
                            item
                            for item in matches
                            if item.get("downstream_action") == "filesystem.find"
                        ]
                    elif (
                        batch_table_semantics.structured_pdf_table_observation_pending(
                            state
                        )
                    ):
                        matches = search_actions(
                            state.domain,
                            "pdf.tables.inspect",
                            limit=search_limit,
                            instruction=state.instruction,
                            stage_actions=self.selected_actions(state),
                            semantic_actions=_strict_search_semantic_actions(state),
                            recent_error=json.dumps(
                                previous_error, ensure_ascii=False, default=str
                            ),
                            excluded_actions=excluded_actions,
                            excluded_routes=excluded_routes,
                            strict_generic=True,
                        )
                        matches = [
                            item
                            for item in matches
                            if item.get("downstream_action")
                            == batch_table_semantics.PDF_TABLE_INSPECT_ACTION
                        ]
                    elif batch_table_semantics._decimal_rate_next_write_target(state) is not None:
                        matches = search_actions(
                            state.domain,
                            "libreoffice_calc range.write",
                            limit=search_limit,
                            instruction=state.instruction,
                            stage_actions=self.selected_actions(state),
                            semantic_actions=_strict_search_semantic_actions(state),
                            recent_error=json.dumps(
                                previous_error, ensure_ascii=False, default=str
                            ),
                            excluded_actions=excluded_actions,
                            excluded_routes=excluded_routes,
                            strict_generic=True,
                        )
                        matches = [
                            item for item in matches
                            if item.get("adapter") == "libreoffice_calc"
                            and item.get("downstream_action") == "range.write"
                        ]
                    elif (
                        batch_table_semantics.native_pdf_table_observation_complete(state)
                        and batch_table_semantics._observed_decimal_rate_matrix(state) is not None
                        and batch_table_semantics.next_post_mutation_route(state)
                        == ("libreoffice_calc", "workbook.save")
                    ):
                        matches = search_actions(
                            state.domain,
                            "libreoffice_calc workbook.save",
                            limit=search_limit,
                            instruction=state.instruction,
                            stage_actions=self.selected_actions(state),
                            semantic_actions=_strict_search_semantic_actions(state),
                            recent_error=json.dumps(
                                previous_error, ensure_ascii=False, default=str
                            ),
                            excluded_actions=excluded_actions,
                            excluded_routes=excluded_routes,
                            strict_generic=True,
                        )
                        matches = [
                            item for item in matches
                            if item.get("adapter") == "libreoffice_calc"
                            and item.get("downstream_action") == "workbook.save"
                        ]
                    elif (
                        not explicit_catalog_route
                        and batch_table_semantics.new_workbook_consumer_pending(state)
                    ):
                        # The source records are complete and the instruction
                        # explicitly requests a new output workbook. Lease the
                        # create route directly instead of probing a live Calc
                        # document that is not part of this workflow.
                        matches = search_actions(
                            state.domain,
                            "libreoffice_calc.workbook.create_new",
                            limit=search_limit,
                            instruction=state.instruction,
                            stage_actions=self.selected_actions(state),
                            semantic_actions=_strict_search_semantic_actions(state),
                            recent_error=json.dumps(
                                previous_error, ensure_ascii=False, default=str
                            ),
                            excluded_actions=excluded_actions,
                            excluded_routes=excluded_routes,
                            strict_generic=True,
                        )
                        matches = [
                            item
                            for item in matches
                            if item.get("adapter") == "libreoffice_calc"
                            and item.get("downstream_action") == "workbook.create_new"
                        ]
                    elif (
                        not explicit_catalog_route
                        and batch_table_semantics.native_pdf_table_observation_complete(
                            state
                        )
                    ) and not any(
                        batch_table_semantics._event_matches_action(
                            event, state, "workbook.inspect"
                        )
                        and getattr(event, "executed", False)
                        for event in getattr(state, "events", ())
                    ):
                        # Once all PDFs are observed, the next lease is the
                        # zero-argument live Calc workbook inspection.  This
                        # prevents another natural-language search from
                        # reopening source extraction or selecting create_new.
                        matches = search_actions(
                            state.domain,
                            "libreoffice_calc.workbook.inspect",
                            limit=search_limit,
                            instruction=state.instruction,
                            stage_actions=self.selected_actions(state),
                            semantic_actions=_strict_search_semantic_actions(state),
                            recent_error=json.dumps(
                                previous_error, ensure_ascii=False, default=str
                            ),
                            excluded_actions=excluded_actions,
                            excluded_routes=excluded_routes,
                            strict_generic=True,
                        )
                        matches = [
                            item
                            for item in matches
                            if item.get("adapter") == "libreoffice_calc"
                            and item.get("downstream_action") == "workbook.inspect"
                        ]
                    elif (
                        not explicit_catalog_route
                        and (
                            batch_table_semantics.requested_fields_complete(state)
                            or batch_table_semantics.native_pdf_table_observation_complete(
                                state
                            )
                        )
                        and not batch_table_semantics.inspection_pending(state)
                        and batch_table_semantics.observed_created_table(state) is None
                        and any(
                            batch_table_semantics._event_matches_action(
                                event, state, "workbook.inspect"
                            )
                            for event in getattr(state, "events", ())
                            if getattr(event, "executed", False)
                        )
                    ):
                        # The live workbook identity has been observed, but no
                        # mutation has occurred yet.  Keep the next planning
                        # step observation-derived as well: a natural-language
                        # GUI search must not reopen create_new or filesystem
                        # discovery; it must return the bounded range reader.
                        matches = search_actions(
                            state.domain,
                            "libreoffice_calc.range.read",
                            limit=search_limit,
                            instruction=state.instruction,
                            stage_actions=self.selected_actions(state),
                            semantic_actions=_strict_search_semantic_actions(state),
                            recent_error=json.dumps(
                                previous_error, ensure_ascii=False, default=str
                            ),
                            excluded_actions=excluded_actions,
                            excluded_routes=excluded_routes,
                            strict_generic=True,
                        )
                        matches = [
                            item
                            for item in matches
                            if item.get("adapter") == "libreoffice_calc"
                            and item.get("downstream_action") == "range.read"
                        ]
                    if (
                        not explicit_catalog_route
                        and state.domain == "multi_apps"
                        and (
                            batch_table_semantics.requested_fields_complete(state)
                            or batch_table_semantics.native_pdf_table_observation_complete(
                                state
                            )
                        )
                    ):
                        matches = [
                            item
                            for item in matches
                            if item.get("action") != "adapter.call"
                            or batch_table_semantics.batch_route_allowed_after_completion(
                                state, str(item.get("downstream_action", ""))
                            )
                        ]
                        # If the model searched for an optional source-inspection
                        # route after the batch is complete, the stage filter may
                        # intentionally remove every match. Re-run discovery for
                        # the generic workbook consumer so the model can continue
                        # without repeating an already-complete source search.
                        if (
                            not explicit_catalog_route
                            and not matches
                            and batch_table_semantics.observed_created_table(state) is None
                        ):
                            matches = search_actions(
                                state.domain,
                                "workbook.create_new",
                                limit=search_limit,
                                instruction=state.instruction,
                                stage_actions=self.selected_actions(state),
                                semantic_actions=_strict_search_semantic_actions(state),
                                strict_generic=True,
                            )
                if (
                    state.domain == "multi_apps"
                    and not explicit_catalog_route
                    and state.requested_mail_recipient_target()
                    and state.source_read_handoff_pending()
                ):
                    # During the post-read mail lease, unrelated Calc or
                    # spreadsheet matches are not actionable discovery. Keep
                    # the model on the exact owning application until the
                    # recipient writer route is returned.
                    matches = [
                        item
                        for item in matches
                        if state._catalog_has_mail_recipient_route([item])
                    ]
                eligible_search_routes = None
                if pdf_table_selection.active(state):
                    eligible_search_routes = pdf_table_selection.allowed_routes(state)
                    exact_eligible_query = any(query.casefold() == f"{adapter}.{downstream}".casefold() for adapter, downstream in eligible_search_routes)
                    if exact_eligible_query:
                        # Resolve the model's exact eligible public route without
                        # legacy instruction ranking or unrelated stage filters.
                        matches = search_actions(state.domain, query, limit=search_limit, strict_generic=True)
                    elif not explicit_catalog_route and len(eligible_search_routes) == 1:
                        adapter, downstream_action = next(iter(eligible_search_routes))
                        matches = search_actions(state.domain, f"{adapter}.{downstream_action}", limit=search_limit, strict_generic=True)
                    matches = [item for item in matches if (item.get("adapter"), item.get("downstream_action")) in eligible_search_routes]
                state.expanded_actions = list(
                    dict.fromkeys(
                        [*state.expanded_actions, *(item["action"] for item in matches)]
                    )
                )
                event.executed = True
                event.proposed["kind"] = "catalog"
                visible_matches = [
                    {key: value for key, value in item.items() if key != "signature"}
                    for item in matches
                ]
                event.result = {
                    "status": "ok",
                    "executed": True,
                    "matches": visible_matches,
                    "eligible_routes": [f"{adapter}.{downstream}" for adapter, downstream in sorted(eligible_search_routes)] if eligible_search_routes is not None else None,
                    "next_step_hint": pdf_table_selection.stage_hint(state) if eligible_search_routes is not None else None,
                    "recovery": {
                        "trigger": "repeated_action" if active_blocks else None,
                        "excluded_actions": sorted(
                            {str(safe_action(action)) for action in excluded_actions}
                        ),
                        "excluded_routes": [
                            {
                                "adapter": safe_action(adapter),
                                "action": safe_action(action),
                            }
                            for adapter, action in sorted(excluded_routes)
                        ],
                        "blocks": _model_visible_recovery_blocks(active_blocks),
                        "last_failure": last_failure_summary(state),
                        "search_limit": search_limit,
                        "fallback_reason": "the same action and normalized arguments reached the same structured error twice; retry only with materially different arguments, choose another generic action, use GUI fallback, or fail explicitly"
                        if active_blocks
                        else None,
                    },
                }
            elif tool == "gui_action":
                if self.gui_executor is None:
                    raise RuntimeError("GUI executor is not configured")
                gui_contract_errors = (
                    spreadsheet_open_semantics.gui_request_contract_errors(state)
                )
                if gui_contract_errors:
                    raise ValueError(gui_contract_errors[0])
                coordinate_frame = proposal.get("_gui_coordinate_frame")
                if screenshot is not None:
                    _, screenshot_frame = self._prepare_model_image(screenshot)
                    if (
                        coordinate_frame is not None and screenshot_frame is not None
                        and coordinate_frame != screenshot_frame
                    ):
                        raise ValueError("GUI coordinate frame does not match the current screenshot")
                    coordinate_frame = screenshot_frame or coordinate_frame
                gui_arguments = arguments
                if coordinate_frame is not None:
                    gui_arguments = map_gui_coordinates(arguments, coordinate_frame)
                    event.proposed["gui_coordinate_frame"] = copy.deepcopy(coordinate_frame)
                event.validated = True
                command = self._gui_command(gui_arguments)
                event.proposed.update({"kind": "gui", "command": command})
                event.proposed["gui_arguments"] = copy.deepcopy(gui_arguments)
                if policy_error := repeated_gui_action_error(
                    state.events,
                    command=command,
                    arguments=gui_arguments,
                    step=event.step,
                    block_window_steps=ACTION_BLOCK_WINDOW_STEPS,
                ):
                    raise RepeatedRequestBlocked(policy_error)
                result = self.gui_executor(
                    {**gui_arguments, "command": event.proposed["command"]}
                )
                event.executed = bool(result.get("executed"))
                event.result = (
                    sanitize_gui_result_for_model(result.get("result"))
                    if event.executed
                    else None
                )
                event.error = result.get("error") if not event.executed else None
            elif tool == "gui_request":
                # The planner selects only the visual intent. Holo supplies the
                # coordinate-bearing action; the common GUI gateway executes it
                # and returns a result that is audited on the next turn.
                jsonschema.validate(arguments, GUI_REQUEST_SCHEMA)
                gui_contract_errors = (
                    spreadsheet_open_semantics.gui_request_contract_errors(
                        state, arguments.get("intent")
                    )
                )
                if gui_contract_errors:
                    raise ValueError(gui_contract_errors[0])
                event.validated = True
                event.proposed.update(
                    {
                        "kind": "gui",
                        "delegation": "planner_to_holo",
                        "planner_model_requested": self.config.model,
                    }
                )
                request_signature_arguments = {
                    "action": "gui_request",
                    **copy.deepcopy(arguments),
                }
                event.proposed["gui_request_arguments"] = copy.deepcopy(
                    request_signature_arguments
                )
                if policy_error := repeated_gui_action_error(
                    state.events,
                    command="holo.gui_request",
                    arguments=request_signature_arguments,
                    step=event.step,
                    block_window_steps=ACTION_BLOCK_WINDOW_STEPS,
                    blocked_action="gui_request",
                ):
                    raise RepeatedRequestBlocked(policy_error)
                grounding_result = self._execute_holo_gui_request(
                    arguments,
                    screenshot
                    if screenshot is not None
                    else getattr(self, "_latest_screenshot", None),
                )
                audit_arguments = self._holo_audit_arguments(grounding_result)
                if audit_arguments is not None:
                    event.proposed["gui_arguments"] = audit_arguments
                grounding = grounding_result.get("grounding")
                if isinstance(grounding, dict):
                    # Keep the exact Holo payload and prepared representation in
                    # the immutable event, while model projections retain only
                    # the sanitized action result.
                    event.proposed["holo_grounding"] = copy.deepcopy(grounding)
                prepared = grounding_result.get("prepared_action")
                if isinstance(prepared, dict):
                    command = prepared.get("command")
                    if isinstance(command, str):
                        event.proposed["command"] = command
                event.executed = bool(grounding_result.get("executed"))
                event.result = (
                    sanitize_gui_result_for_model(grounding_result.get("result"))
                    if event.executed
                    else None
                )
                event.error = (
                    None
                    if event.executed
                    else grounding_result.get(
                        "error",
                        {
                            "type": "HoloGuiExecutionError",
                            "detail": "the Holo GUI action was not executed",
                        },
                    )
                )
            elif tool == "propose_done":
                event.validated = True
                event.proposed["kind"] = "completion"
                completion_gate = self._generic_completion_gate
                structural_gate = completion_gate(state)
                gate = completion_gate(state, arguments)
                response_errors = completion_response_contract_errors(proposal)
                if response_errors:
                    gate = {
                        **gate,
                        "passed": False,
                        "missing": list(
                            dict.fromkeys([*response_errors, *gate["missing"]])
                        ),
                    }
                event.executed = bool(gate["passed"])
                event.result = (
                    {"status": "ok", "executed": True, "gate": gate}
                    if gate["passed"]
                    else None
                )
                event.error = (
                    None
                    if gate["passed"]
                    else completion_recovery.completion_rejection_error(
                        gate,
                        structural_gate,
                        response_errors,
                        completion_claim_contradictions(arguments),
                    )
                )
                if gate["passed"]:
                    # The full gate is the final review. A passed claim must
                    # not create another model turn that can reopen the task.
                    state.pending_terminal = None
                    state.pending_model_audit = None
                    state.done = True
                else:
                    state.completion_rejections += 1
            elif tool == "fail_task":
                event.validated = True
                event.executed = True
                event.proposed["kind"] = "failure"
                event.result = {
                    "status": "failed",
                    "executed": True,
                    "reason": arguments["reason"],
                }
                if getattr(state, "defer_terminal_audit", False):
                    state.pending_terminal = {
                        "status": "failed",
                        "tool": "fail_task",
                        "event_step": event.step,
                    }
                else:
                    state.failed = True
            elif (
                organization_skip_handled
                or organization_check_handled
                or tool in {table_ratio_compute.TOOL_NAME, pdf_table_selection.TOOL_NAME}
            ):
                pass
            else:
                raise ValueError(f"unknown or unavailable tool: {tool}")
        except RepeatedRequestBlocked as exc:
            event.error = exc.error
        except Exception as exc:
            if tool == "propose_done":
                completion_gate = self._generic_completion_gate
                event.error = completion_recovery.completion_parse_error(
                    completion_gate(state), exc
                )
                state.completion_rejections += 1
            else:
                if tool == VERIFY_TOOL and callable(getattr(exc, "trace_record", None)):
                    event.proposed["checker_failure_trace"] = exc.trace_record()
                event.error = {
                    "type": type(exc).__name__,
                    "detail": str(exc),
                    "executed": False,
                }
                if tool == VERIFY_TOOL and getattr(exc, "schema_hints", None):
                    event.error["checker_schema_hints"] = list(exc.schema_hints)
            event.executed = False
        event.duration_seconds = round(time.monotonic() - started, 3)
        event.result = sanitize_agent_visible_result(event.result, state.task_id)
        event.error = sanitize_agent_visible_result(event.error, state.task_id)
        state.events.append(event)
        if event.executed and state.filesystem_move_requested():
            progress = state.filesystem_organization_progress(model_visible=True)
            if isinstance(event.result, dict):
                context_hint = event.result.get("context_hint")
                if isinstance(context_hint, dict):
                    context_hint["organization_progress"] = progress
                else:
                    event.result["organization_progress"] = progress
        self._block_repeated_error(state)
        event.error = sanitize_agent_visible_result(event.error, state.task_id)
        return event

    @staticmethod
    def _block_repeated_error(state: RuntimeState) -> None:
        if len(state.events) < 2:
            return
        current = state.events[-1]
        if is_tools_search_provenance_error(current.error):
            return
        if current.executed or (
            isinstance(current.error, dict)
            and current.error.get("type") == "RepeatedActionBlocked"
        ):
            return

        def event_key(event: Any) -> tuple[Any, ...]:
            proposed = event.proposed
            action = str(proposed.get("action") or proposed.get("tool") or "")
            identity = canonical_action_request(
                state.domain,
                action,
                proposed.get("arguments", {}),
            )
            return (
                proposed.get("kind"),
                identity[:2],
                argument_signature(identity[2]),
                error_signature(event.error),
            )

        current_proposed = current.proposed
        current_action = str(
            current_proposed.get("action") or current_proposed.get("tool") or ""
        )
        current_identity = canonical_action_request(
            state.domain,
            current_action,
            current_proposed.get("arguments", {}),
        )
        current_key = event_key(current)
        repeated = next(
            (
                previous
                for previous in reversed(state.events[:-1])
                if not previous.executed
                and event_key(previous) == current_key
                and not request_block_is_stale(
                    state.events, blocked_at_step=previous.step
                )
            ),
            None,
        )
        if repeated is not None:
            signature = error_signature(current.error)
            arguments_signature = argument_signature(current_identity[2])
            blocked_action = current_proposed.get("action") or current_proposed.get(
                "tool"
            )
            current.error = {
                "type": "RepeatedActionBlocked",
                "detail": "the same action and normalized arguments reached the same structured error twice; the exact request is blocked for this episode, so change the arguments, replan, or search",
                "executed": False,
                "previous_step": repeated.step,
                "previous_error": current.error,
                "blocked_action": blocked_action,
                "argument_signature": arguments_signature,
                "error_signature": signature,
                "block_scope": "episode",
                "fallback_reason": "same_action_same_arguments_same_error_twice",
            }

    def step(
        self, state: RuntimeState, screenshot: bytes, screenshot_path: str | None = None
    ) -> ExecutionEvent:
        proposal = self.propose(state, screenshot)
        return self.execute_proposal(state, proposal, screenshot_before=screenshot_path)
