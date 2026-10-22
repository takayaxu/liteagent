"""Extracted LiteAgent support module; keep application semantics generic."""

from __future__ import annotations
import base64
import copy
import hashlib
import io
import json
import re
from typing import Any

from PIL import Image
from .adapter_results import (
    adapter_context_hint as adapter_context_hint,
    compact_adapter_body as compact_adapter_body,
    compact_execution_summary_for_model as compact_execution_summary_for_model,
    contains_text_batch_context as contains_text_batch_context,
)
from .completion_policy import (
    completion_claim_contradictions as completion_claim_contradictions,
)
from .safety import assert_agent_surface_safe as assert_safe_agent_surface
from .source_execution_semantics import protocol_guidance
from .tool_catalog import instruction_requests_code_execution, tool_name
from .instruction_semantics import strict_instruction_required_actions
from .state_model import RuntimeState
from .strict_contracts import RANGE_WRITE_FACADES
from .recovery_surface import last_failure_summary
from . import batch_table_semantics, table_ratio_compute
from . import completion_review
from .search_recovery_tools import constrain_adapter_call_routes


# Ordinary protocol retries stay deliberately small.  A failed call after a
# successful multi-file read is different: the batch is the model's working
# set, so it gets a larger but still bounded projection budget.  The complete
# event ledger remains out of band and is never sent to the model.
MODEL_PROTOCOL_RECOVERY_MAX_CHARS = 9_000
MODEL_BATCH_RECOVERY_MAX_CHARS = 16_000
# A form transfer needs its exact field names and the previously read source
# together. The ordinary 9K retry discarded both after an output-token limit.
MODEL_FORM_RECOVERY_MAX_CHARS = 24_000
# A truncated tool call still needs enough room to emit a concrete tool call
# after inspecting a large table/document result.  2k was insufficient for
# the Writer table-color task: the model spent the whole recovery turn
# re-enumerating cells and never reached the first mutation.  Keep this
# bounded and below the provider context limit, but restore a usable budget.
MODEL_TRUNCATION_RECOVERY_MIN_TOKENS = 4_096


def _contains_pdf_form_observation(value: Any) -> bool:
    if isinstance(value, dict):
        if (
            value.get("action") == "pdf.form.inspect"
            or value.get("downstream_action") == "pdf.form.inspect"
        ):
            return True
        return any(_contains_pdf_form_observation(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_pdf_form_observation(item) for item in value)
    return False


class AgentProtocolMixin:
    @staticmethod
    def _execution_recovery_pending(state: RuntimeState) -> bool:
        """Use a bounded state projection after a rejected model action.

        A validation or target error is part of the truthful episode ledger,
        but replaying the full batch observation on the next turn can consume
        the model's entire generation budget before it reaches a correction.
        Catalog and completion failures have their own bounded surfaces and do
        not need this projection.
        """
        # A same-VM soft restart can leave the triggering event executed while
        # its transient recovery handoff is still pending. Detect that state
        # before inspecting the latest event so the first replan turn remains
        # bounded instead of falling back to the full transcript.
        if isinstance(getattr(state, "recovery_context", None), dict) or isinstance(
            getattr(state, "pending_runner_replan", None), dict
        ):
            return True
        events = getattr(state, "events", ())
        if not events:
            return False
        latest = events[-1]
        proposed = getattr(latest, "proposed", None)
        return bool(
            not getattr(latest, "executed", False)
            and isinstance(getattr(latest, "error", None), dict)
            and isinstance(proposed, dict)
            and proposed.get("kind") in {"adapter", "gui"}
        )

    def tool_catalog_hash(self, state: RuntimeState) -> str:
        tools = self.tools(state)
        encoded = json.dumps(tools, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _system_message(
        self,
        state: RuntimeState,
        *,
        tools: list[dict[str, Any]] | None = None,
        protocol_recovery: bool = False,
        execution_recovery: bool = False,
        protocol_error: dict[str, Any] | None = None,
    ) -> str:
        environment = (
            f" Active terminal working directory: {state.working_directory}."
            if state.working_directory
            else ""
        )
        source_workflow_guidance = (
            protocol_guidance(state.instruction)
            if state.domain == "multi_apps"
            else None
        )
        calc_guidance = (
            " For Calc table edits, use the observed cell labels and coordinates: a row "
            "whose first populated cell is Total or Subtotal is a row-wide summary. "
            "When its numeric cells are blank, fill every blank period cell and the "
            "final Total cell; do not treat only the last column as the target. For a "
            "summary row r over detail rows s:e, period column c is =SUM(c_s:c_e) "
            "(vertical), and the final Total cell is =SUM(first_period_r:last_period_r) "
            "(horizontal across the summary row); do not put a detail-row formula such "
            "as =SUM(B3:E3) into a summary cell. Also fill any blank trailing Total "
            "cells on detail rows; those use the horizontal detail-row formula "
            "=SUM(first_period_r:last_period_r). When both target lists are observed, "
            "cover their union in the same formula mutation. A summary entry's "
            "period_cells are vertical-SUM targets and its final_total_cell is the "
            "horizontal-SUM target."
            if state.domain == "libreoffice_calc"
            else ""
        )
        rate_handoff = ""
        if state.domain == "multi_apps":
            matrix = batch_table_semantics._observed_decimal_rate_matrix(state)
            target = batch_table_semantics._observed_decimal_rate_target(state)
            if matrix is not None and target is not None:
                if (
                    not batch_table_semantics.inspection_pending(state)
                    and not batch_table_semantics.mutation_and_save_complete(state)
                ):
                    rate_handoff = (
                        " A read-only table.ratio_matrix.compute result is available. "
                        f"Submit its model-visible values with the exposed {batch_table_semantics.WRITE_ACTION} "
                        f"to {target['sheet']}!{target['range']}. Preserve its row and column order."
                    )
        calc_guidance += rate_handoff
        code_execution = source_workflow_guidance or (
            " For a source-code task that explicitly asks you to run or execute the code, read the relevant source and use command.run for a finite baseline reproduction before the first source mutation. After editing, use command.run again for finite verification before propose_done. For an interactive or long-running program, use a bounded import, syntax check, or focused test instead of launching it indefinitely."
            if state.domain == "multi_apps"
            and instruction_requests_code_execution(state.instruction)
            else ""
        )
        replan = (
            " On every turn, discard any previously planned tool call and replan from the latest "
            "observation plus the currently exposed schema; those are the sole source of truth "
            "and override older context. If the schema exposes one route, call that route even "
            "if an earlier turn suggested another action. For pdf.extract_text_batch, "
            "cwd_source must be exactly one of its enum values (active_terminal, home, or "
            "explicit); never put a directory path in cwd_source. Use cwd_path only with "
            "cwd_source=explicit."
            + (
            " The Runner detected a bounded no-progress cycle. Reconsider the remaining user-visible "
            "outcome and choose one materially different model-selected action or tool search; do not "
            "repeat the same operation and arguments."
            if state.pending_runner_replan is not None
            else ""
            )
        )
        pending_terminal = getattr(state, "pending_terminal", None)
        terminal_audit_guidance = (
            " The previous terminal control result is waiting for one audit turn. "
            "Acknowledge the same terminal tool once. Successful completion claims "
            "already end immediately after final review and require no audit turn."
            if isinstance(pending_terminal, dict)
            else ""
        )
        failure = last_failure_summary(state)
        failure_guidance = (
            " The latest model-selected call failed or was rejected. Inspect "
            "the reported cause and partial results: re-observe, search, choose a "
            "different public action, or retry only with materially different "
            "arguments. Never replay the identical request."
            if failure
            else ""
        )
        correction_guidance = ""
        if isinstance(failure, dict) and isinstance(failure.get("correction"), str):
            correction_guidance = (
                " Inspect the structured rejection and source references, then submit "
                "your corrected arguments through the original public API. The runner "
                "does not replace values or execute a confirmation as a mutation. Detail: "
                + failure["correction"]
            )
        missing_fields: list[str] = []
        if isinstance(protocol_error, dict):
            raw_fields = protocol_error.get("missing_fields")
            if isinstance(raw_fields, list):
                missing_fields = [
                    field
                    for field in raw_fields
                    if isinstance(field, str)
                    and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", field)
                ][:8]
        missing_guidance = (
            " Required fields missing from the previous call: "
            + ", ".join(missing_fields)
            + "."
            if missing_fields
            else ""
        )
        # A schema-only list is easy for a small thinking model to acknowledge
        # without changing its next call.  Add one bounded, action-agnostic
        # repair sentence that makes the required fields operational while
        # leaving every semantic value to the model.  In particular, large
        # range writes can be built from a one-cell source followed by the
        # public fill action; this avoids spending the entire recovery budget
        # constructing a giant inline matrix before emitting a call.
        required_call_guidance = ""
        if missing_fields and isinstance(protocol_error, dict):
            failed_tool = protocol_error.get("tool")
            if isinstance(failed_tool, str) and re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_.:-]{0,119}", failed_tool
            ):
                required_call_guidance = (
                    f" The previous {failed_tool} call was incomplete. Emit that "
                    "same public action only with every required top-level field "
                    "present; for a large range, use a small valid source write "
                    "and then the documented fill action instead of omitting a "
                    "required field."
                )
        repeat_cue = ""
        if protocol_recovery and isinstance(protocol_error, dict):
            recovery_attempt = protocol_error.get("recovery_attempt")
            if isinstance(recovery_attempt, int) and recovery_attempt >= 2:
                repeat_cue = (
                    f" Repeated protocol recovery after {recovery_attempt} rejected "
                    "responses. None of those calls executed. Reconsider the current "
                    "error; do not repeat the malformed call or end with reasoning alone."
                )
        schema_hints: list[str] = []
        if isinstance(protocol_error, dict):
            raw_hints = protocol_error.get("schema_hints")
            if isinstance(raw_hints, list):
                for raw_hint in raw_hints[:8]:
                    if not isinstance(raw_hint, str):
                        continue
                    # Hints are generated from schema keywords by the model
                    # client.  Bound and normalize them again at the prompt
                    # boundary so a malformed transport cannot add prose.
                    hint = " ".join(raw_hint.split())[:180]
                    if hint and hint not in schema_hints:
                        schema_hints.append(hint)
        schema_guidance = (
            " Public schema rules violated by the previous call: "
            + "; ".join(schema_hints)
            + ". Satisfy these rules exactly; do not copy the rejected arguments."
            if schema_hints
            else ""
        )
        allowed_route_guidance = ""
        route_mismatch_guidance = ""
        if isinstance(protocol_error, dict):
            raw_routes = protocol_error.get("allowed_routes")
            allowed_routes: list[tuple[str, str]] = []
            if isinstance(raw_routes, list):
                for route in raw_routes[:8]:
                    if not isinstance(route, dict):
                        continue
                    adapter = route.get("adapter")
                    action = route.get("action")
                    if not (
                        isinstance(adapter, str)
                        and isinstance(action, str)
                        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,119}", adapter)
                        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,119}", action)
                    ):
                        continue
                    pair = (adapter, action)
                    if pair not in allowed_routes:
                        allowed_routes.append(pair)
            if allowed_routes:
                rendered_routes = "; ".join(
                    f"adapter={adapter}, action={action}"
                    for adapter, action in allowed_routes
                )
                allowed_route_guidance = (
                    " The current exposed route lease is authoritative and overrides "
                    "all older plans. The only allowed route(s) are: "
                    + rendered_routes
                    + ". Emit the matching adapter/action now. Do not call a route "
                    "from an earlier turn, search for the old route, or place the "
                    "old action under another payload field."
                )
                if protocol_error.get("reason") == "tool route is not in the exposed allowlist":
                    rejected_route = protocol_error.get("rejected_route")
                    rejected_text = ""
                    if isinstance(rejected_route, dict):
                        rejected_adapter = rejected_route.get("adapter")
                        rejected_action = rejected_route.get("action")
                        if isinstance(rejected_adapter, str) and isinstance(
                            rejected_action, str
                        ):
                            rejected_text = (
                                f" The rejected stale route was {rejected_adapter}."
                                f"{rejected_action}; do not emit it again."
                            )
                    route_mismatch_guidance = (
                        " The previous response selected an adapter/action outside this "
                        "allowlist and was rejected without execution. Do not rely on "
                        "or repeat that old route; emit exactly one call using the "
                        "currently exposed adapter/action pair."
                        + rejected_text
                    )
        if protocol_recovery or execution_recovery:
            recovery_guidance = (
                (
                    (
                        " Bounded execution recovery is active because the previous "
                        "model-selected action was rejected or did not execute. Use the "
                        "truthful error category and choose a materially different public "
                        "action or argument set; never replay the identical request."
                    )
                    if execution_recovery
                    else (
                        " Protocol recovery is active because the previous model response "
                        "was not one complete schema-valid structured call. Emit exactly "
                        "one complete call from the provided tools now; keep reasoning "
                        "brief and do not end with prose. Do not invent, rewrite, or "
                        "inherit arguments. If uncertain, choose the safest available "
                        "observation action."
                    )
                )
                + missing_guidance
                + required_call_guidance
                + schema_guidance
                + allowed_route_guidance
                + route_mismatch_guidance
                + repeat_cue
            )
        else:
            recovery_guidance = ""
        hybrid_gui = (
            getattr(self, "holo_grounder", None) is not None
            or getattr(self, "holo_gui_gateway", None) is not None
        )
        gui_guidance = (
            " Use gui_request when a visible GUI operation is required: describe the "
            "single intended operation and target without coordinates; Holo will ground "
            "it against the latest screenshot and return one gui_action for the gateway."
            " When the user explicitly names a built-in application feature, invoke "
            "that feature, not a similar-looking result assembled with unrelated edits. "
            "If no Adapter exposes it, use the GUI to find its native command."
            " GUI changes can invalidate earlier inspection results. Before editing a "
            "newly created object, use an available structural inspection to read its "
            "current contents; a placeholder does not mean the whole object is blank."
            if hybrid_gui
            else " Use gui_action only with a concrete reason that deterministic tools cannot satisfy the operation."
        )
        completion_readback = (
            "Before propose_done, save the requested result and check it after the final change. "
            "For Adapter changes, use structural read-back. For Holo GUI changes, review the "
            "latest screenshot: executed=true confirms the input ran, not that the intended "
            "setting or saved file is correct. Do not repeat a GUI change through an Adapter "
            "merely to supply a mutation record. An Adapter result may describe an object on "
            "a non-active worksheet; the screenshot can remain on the active sheet and is not "
            "evidence that the Adapter result is absent. Use one structural inspect call "
            "instead of switching sheets or recreating the object."
            if hybrid_gui
            else "Before propose_done, save when the application has a save action and "
            "structurally inspect the result after the final mutation. An Adapter result may "
            "describe an object on a non-active worksheet; use structural inspect rather than "
            "switching sheets or recreating it."
        )
        completion_readback += (
            " If the latest successful action result explicitly confirms that the current "
            "document was saved after its changes, the save requirement is already satisfied. "
            "Do not save it again merely to satisfy that requirement; structurally inspect "
            "its final state before proposing completion. Later changes require fresh save "
            "evidence; a save before those changes is not sufficient."
        )
        if completion_review.review_ready(state, self._generic_completion_gate(state)):
            completion_readback += (
                " The implemented completion checks currently pass. Compare the observed "
                "result with every user requirement and target before propose_done. "
                "Review the final observations already in context; a single target's "
                "verification does not prove a whole batch. If every clause is satisfied, "
                "call propose_done now. Its full gate is the final review: acceptance "
                "ends execution immediately without another inspection or confirmation. "
                "If self-review identifies an actual discrepancy, call completion_revise "
                "with the observed state, required state and correction; a failed review "
                "opens inspection and repair tools. Do not repeat satisfied inspections."
            )
        failure_guidance += correction_guidance
        failure_guidance += (
            " For filesystem organization, submit the current classification to "
            "organization__verify_current after inspecting the object. A passed independent "
            "check is required before moving or retaining it; opening alone is not inspection. "
            "organization__skip_current is available only when retention has been verified "
            "to satisfy the instruction. For a natural-language read search, use the returned exact reader "
            "route when it matches the current object's required reader and do not repeat "
            "the same tools_search query."
        )
        return f"""You are a lightweight OSWorld desktop agent. Perform the user's task in the current VM. Call exactly one provided tool per turn. Prefer deterministic Adapter tools over GUI. If a structural inspection tool and a dependent mutation tool are both provided, call the inspection tool first, then use the mutation with the exact documented schema; if only inspection is provided, call it and do not stop with prose because a later turn may expose the dependent action. When structural inspect output already identifies the requested object and an exposed Adapter action accepts that identifier, call the Adapter directly; it does not require the object to be selected or visible in the GUI. Do not navigate or click merely to select an object that inspect already identified. A tool result with executed=false is not a confirmed success; inspect the error and any partial results before choosing a correction. A rejected call did not run, but an execution or verification failure may have changed state. Never claim success from a proposed call. Use tools_search if a required public action is not exposed. For filesystem organization tasks, inspect both files and directories (use filesystem.find with kind=any) before classifying inputs, and exclude the destination category folders themselves from the source set. If a successful organization search used kind=file, it explicitly omitted directories; immediately issue one follow-up filesystem.find with kind=any before moving anything. Interpret \"move\", \"place\", \"put\", or \"organize\" as moving each selected object with filesystem.rename; use filesystem.copy or filesystem.copy_to_directories only when the instruction explicitly requests a copy or duplicate and the source should remain. When the instruction requests content analysis or a filename is ambiguous, read the relevant file content with the bounded public reader before classifying it; do not infer its category from a generic extension or name alone. For organization categories, follow the user's classification criteria and exact destination folder names. Use observed content to decide whether to move the current object or explicitly retain it with organization__skip_current. Once exact paths are observed, do not repeat equivalent searches: classify the remaining observed objects and move them with exact source/destination pairs. Do not repeat an identical successful read for the same source and offset; use its observed next_start_char for the next window, or proceed to the dependent mutation once the requested fields are visible. If range.write rejects model-supplied rows for placeholder values or sort order, correct those rows in memory, keep one row per source document, remove only invalid placeholder cells, reorder by the requested observed sort column, and retry range.write; do not reread a source that already supplied the requested fields. For Thunderbird messages.query, select_from chooses which end of the date-sorted matches is selected, while order only controls the returned order; for a request for the latest or most recent N messages from earliest to most recent, use select_from=\"latest\" and order=\"ascending\". When extracting fields from multiple source documents, preserve the instruction's requested cardinality: create one output record per source document when it asks for one entity per document, and do not expand that entity into related items such as coauthors unless requested. After source observation is complete, assemble only the fields requested by the user, retaining their source references. Never mix values across documents. workbook.create_new creates a blank unsaved workbook only; explicitly call range.write for values, range.format for display and workbook.save_as for the output file. For percentage display store a fraction and use number_format=0.00%. Do not submit null, a prefix-only value, or a guessed value; if the mapping is not visible, use the bounded continuation once. {gui_guidance}{calc_guidance} For people, objects, scenes, layout, or other visual appearance in image files, open the image and inspect the screenshot; OCR only extracts visible text and cannot classify visual subjects. When the instruction explicitly requires command-line or terminal execution, set provenance=\"shell_history\" on each relevant command.run or terminal.show_output call. {completion_readback} A successful Adapter result with verification_passed=true and a matching structural read-back already satisfies that requirement; propose_done instead of calling an unrelated verifier. The completion gate may reject unsupported completion and return missing items. Before propose_done, compare every clause in the instruction against the truthful action ledger. Never claim an argument, value, target, or operation that is absent from an executed=true event; use tools_search to continue when any clause lacks evidence. Benchmark task identifiers, evaluator state, golden artifacts, and task-specific execution routes are unavailable; solve only from the instruction, screenshot, and public generic tools. Task domain: {state.domain}.{code_execution}{environment}{replan}{failure_guidance}{recovery_guidance}{terminal_audit_guidance}"""

    def assert_agent_surface_safe(
        self,
        state: RuntimeState,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> None:
        assert_safe_agent_surface(task_id=state.task_id, messages=messages, tools=tools)

    @staticmethod
    def _bind_system_message_to_tools(
        message: str,
        state: RuntimeState,
        tools: list[dict[str, Any]],
    ) -> str:
        """Make generic workflow prose agree with the current tool lease.

        The base prompt contains broad first-turn guidance, while organization
        turns deliberately expose a much narrower state-dependent surface. A
        small model can otherwise follow the old discovery instruction even
        after that route has been removed from the schema.
        """
        names: set[str] = set()
        routes: list[tuple[str, str]] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if isinstance(name, str):
                names.add(name)
            if name != "adapter__adapter_call":
                continue
            parameters = function.get("parameters")
            raw_routes = (
                parameters.get("x-allowed-routes")
                if isinstance(parameters, dict)
                else None
            )
            if not isinstance(raw_routes, list):
                continue
            for route in raw_routes:
                if not isinstance(route, dict):
                    continue
                adapter = route.get("adapter")
                action = route.get("action")
                pair = (adapter, action)
                if (
                    isinstance(adapter, str)
                    and isinstance(action, str)
                    and pair not in routes
                ):
                    routes.append(pair)

        rendered_names = ", ".join(sorted(names)) or "none"
        rendered_routes = "; ".join(
            f"{adapter}.{action}" for adapter, action in routes
        )
        lease = (
            " The current tool lease is authoritative for this turn. Call exactly one "
            f"function from this list: {rendered_names}."
            + (f" Downstream routes: {rendered_routes}." if rendered_routes else "")
            + " Do not emit, name, or place an action from an earlier turn in the "
            "response; an action not present here is unavailable, even if the task "
            "normally uses it."
        )
        message = message.replace(
            " Prefer deterministic Adapter tools over GUI.",
            " Prefer deterministic Adapter tools over GUI." + lease,
            1,
        )
        if "tools_search" in names:
            search_guidance = (
                " Use tools_search only when the required public action is not in "
                "the current tool lease."
            )
            completion_guidance = " use tools_search to continue when any clause lacks evidence."
        else:
            search_guidance = (
                " If the required action is not in the current tool lease, do not "
                "invent or search for it; use one of the exposed transitions or wait "
                "for the next state."
            )
            completion_guidance = " continue only with evidence from the current tool lease."
        message = message.replace(
            " Use tools_search if a required public action is not exposed.",
            search_guidance,
            1,
        )
        message = message.replace(
            " use tools_search to continue when any clause lacks evidence.",
            completion_guidance,
            1,
        )
        if state.filesystem_move_requested():
            observation = state.filesystem_observation_state()
            if ("os", "filesystem.find") in routes and not (isinstance(observation, dict) and observation.get("complete") is True):
                organization_guidance = (
                    " For filesystem organization, use the exposed discovery route to "
                    "inspect both files and directories before classifying inputs. "
                    "Exclude the destination category folders themselves from the source set."
                )
            elif isinstance(observation, dict) and observation.get("complete") is True:
                organization_guidance = (
                    " Filesystem observation is complete. Do not rediscover the root or "
                    "emit an earlier discovery action. Classify only the exact current "
                    "source object. Destination category directories are protected, not sources. "
                    "After observing content, submit the classification for independent "
                    "verification. Move or retain only after a passing check; an object "
                    "advances only after its actual disposition is verified."
                )
            else:
                organization_guidance = (
                    " Filesystem organization is in a later state. Use only the currently "
                    "exposed organization transition; do not emit an unexposed discovery "
                    "or mutation route. Exclude the destination category folders themselves "
                    "from the source set."
                )
            message = re.sub(
                r" For filesystem organization tasks, inspect both files and directories "
                r"\(use filesystem\.find with kind=any\) before classifying inputs, and "
                r"exclude the destination category folders themselves from the source set\. "
                r"If a successful organization search used kind=file, it explicitly omitted "
                r"directories; immediately issue one follow-up filesystem\.find with kind=any "
                r"before moving anything\.",
                organization_guidance,
                message,
                count=1,
            )
        return message

    @staticmethod
    def _image_url(screenshot: bytes) -> str:
        return AgentProtocolMixin._prepare_model_image(screenshot)[0]

    @staticmethod
    def _prepare_model_image(
        screenshot: bytes,
    ) -> tuple[str, dict[str, list[int]] | None]:
        # Desktop captures are commonly 1920x1080 PNGs. Sending the raw PNG
        # as base64 can consume millions of prompt characters on every turn,
        # even when the task is entirely deterministic and does not need GUI
        # detail. Keep enough resolution for visual grounding while bounding
        # the multimodal prompt size. Invalid synthetic bytes used by tests or
        # non-image callers retain the historical passthrough behavior.
        encoded = screenshot
        media_type = "image/png"
        coordinate_frame = None
        try:
            with Image.open(io.BytesIO(screenshot)) as image:
                desktop_size = list(image.size)
                image = image.convert("RGB")
                image.thumbnail((1280, 720), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=70, optimize=True)
                encoded = output.getvalue()
                media_type = "image/jpeg"
                coordinate_frame = {
                    "model_size": list(image.size),
                    "desktop_size": desktop_size,
                }
        except Exception:
            pass
        url = f"data:{media_type};base64," + base64.b64encode(encoded).decode("ascii")
        return url, coordinate_frame

    def _messages(
        self,
        state: RuntimeState,
        screenshot: bytes,
        *,
        tools: list[dict[str, Any]] | None = None,
        protocol_recovery: bool = False,
        execution_recovery: bool | None = None,
        protocol_error: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        from . import read_audit_gate

        read_messages = read_audit_gate.messages(self, state, protocol_error)
        if read_messages is not None and state.pending_terminal is None:
            return read_messages
        organization_context = state.filesystem_move_requested()

        def model_context(limit: int) -> list[dict[str, Any]]:
            if organization_context:
                return state.filesystem_organization_model_context(limit=limit)
            return state.context_summary(limit=limit, strict_generic=True)

        if execution_recovery is None:
            execution_recovery = (
                not protocol_recovery and self._execution_recovery_pending(state)
            )
        pending_rate_row = batch_table_semantics._decimal_rate_next_write_target(state)
        bounded_recovery = protocol_recovery or execution_recovery
        if pending_rate_row is not None and table_ratio_compute.latest_result(state) is not None:
            last_error = state.events[-1].error if state.events else None
            state_text = (
                "Current truthful execution state (earlier PDF reads and computed rows remain in the ledger):\n"
                + json.dumps({
                    "next_action": "libreoffice_calc.range.write",
                    "sheet": pending_rate_row["sheet"],
                    "range": pending_rate_row["range"],
                    "row_keys": pending_rate_row["row_keys"],
                    "computed_values": pending_rate_row["values"],
                    "last_error": last_error,
                }, ensure_ascii=False)
                + "\nSubmit exactly this current row as JSON numbers; do not reuse an earlier row."
            )
        elif bounded_recovery:
            summary = model_context(limit=4)
            recovery_budget = (
                MODEL_FORM_RECOVERY_MAX_CHARS
                if _contains_pdf_form_observation(summary)
                else MODEL_BATCH_RECOVERY_MAX_CHARS
                if contains_text_batch_context(summary)
                else MODEL_PROTOCOL_RECOVERY_MAX_CHARS
            )
            truthful_state = compact_execution_summary_for_model(
                summary,
                max_chars=recovery_budget,
            )
            state_text = (
                "Compact truthful execution state (failed calls may have partial effects):\n"
                + json.dumps(truthful_state, ensure_ascii=False)
                + "\nReturn exactly one tool call now."
            )
        else:
            state_text = (
                "Current truthful execution state (failed calls may have partial effects):\n"
                + json.dumps(
                    model_context(limit=12),
                    ensure_ascii=False,
                )
                + "\nChoose the single next action using the instruction, latest tool results, "
                "and current screenshot."
            )
        # Recompute from the immutable ledger after compaction so old source
        # reads and concrete defects cannot disappear from a short repair turn.
        from .completion_outcomes import completion_outcome_issues

        outcomes = completion_outcome_issues(state)
        if outcomes:
            state_text += "\ncompletion_outcomes:\n" + json.dumps(outcomes, ensure_ascii=False)
        from . import calc_formula_contract

        calculation_evidence = calc_formula_contract.model_evidence(state)
        if calculation_evidence is not None:
            state_text += "\ncalculation_source_cells:\n" + json.dumps(calculation_evidence, ensure_ascii=False)
        message_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": state_text,
            }
        ]
        # Deterministic Adapter turns do not need a repeated desktop image.
        # Keeping the screenshot for GUI-only turns preserves visual grounding
        # while avoiding a large Base64 payload on every PDF/Calc turn.
        tool_names = {
            str(tool.get("function", {}).get("name"))
            for tool in (tools or [])
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        }
        include_screenshot = not tools or "gui_action" in tool_names or not any(
            name == "adapter__adapter_call" for name in tool_names
        )
        evidence = state.filesystem_organization_evidence() if organization_context else None
        if evidence and evidence.get("action") == "desktop.open_path":
            include_screenshot = True
        self._latest_gui_coordinate_frame = None
        if include_screenshot:
            image_url, coordinate_frame = self._prepare_model_image(screenshot)
            if coordinate_frame is not None and (not tools or "gui_action" in tool_names):
                self._latest_gui_coordinate_frame = coordinate_frame
                width, height = coordinate_frame["model_size"]
                message_content[0]["text"] += (
                    f"\nGUI coordinate frame: the attached image is {width}x{height} pixels. "
                    f"For gui_action use pixel coordinates in this image: x/to_x from 0 to {width - 1}, "
                    f"y/to_y from 0 to {height - 1}, origin at the top left. "
                    "Do not use normalized coordinates or scale to desktop resolution yourself; "
                    "the executor maps these image pixels to the desktop."
                )
            message_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                }
            )
        system_message = self._system_message(
            state,
            protocol_recovery=protocol_recovery,
            execution_recovery=bool(execution_recovery),
            protocol_error=protocol_error,
        )
        if tools is not None:
            system_message = self._bind_system_message_to_tools(
                system_message,
                state,
                tools,
            )
        return [
            {
                "role": "system",
                "content": system_message,
            },
            {"role": "user", "content": state.instruction},
            {"role": "user", "content": message_content},
        ]

    def propose(
        self,
        state: RuntimeState,
        screenshot: bytes,
        *,
        protocol_recovery: bool = False,
        execution_recovery: bool | None = None,
        protocol_error: dict[str, Any] | None = None,
        request_timeout_seconds: float | None = None,
        deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        # The execution phase follows immediately after ``propose`` in the
        # Runner.  Retain the exact bytes so a delegated GUI request can be
        # grounded against the same observation without changing the Runner
        # or putting screenshot data into RuntimeState.
        self._latest_screenshot = bytes(screenshot)
        tools = self.tools(state)
        if (
            protocol_recovery
            and isinstance(protocol_error, dict)
            and protocol_error.get("reason") == "tool route is not in the exposed allowlist"
            and isinstance(protocol_error.get("rejected_route"), dict)
            and protocol_error["rejected_route"].get("action") == "filesystem.find"
            and state.domain == "multi_apps"
        ):
            # A stale discovery call after filesystem observation is complete
            # cannot advance the task.  On the recovery turn narrow the
            # visible lease to the dependent mutation routes so the model has
            # no search/read branch to replay.
            tools = constrain_adapter_call_routes(
                tools,
                [
                    ("os", "filesystem.create_directory"),
                    ("os", "filesystem.rename"),
                ],
            )
        messages = self._messages(
            state,
            screenshot,
            tools=tools,
            protocol_recovery=protocol_recovery,
            execution_recovery=execution_recovery,
            protocol_error=protocol_error,
        )
        self.assert_agent_surface_safe(state, messages, tools)
        output_token_budget = self.output_token_budget(state)
        if (
            protocol_recovery
            and isinstance(protocol_error, dict)
            and protocol_error.get("finish_reason") == "length"
            and not self._native_pdf_compact_turn(state)
        ):
            # A recovery turn must have at least enough room to emit the next
            # structured call after a large inspection.  ``min`` preserved a
            # 2048-token caller cap, so the model kept re-enumerating the
            # Writer table and was truncated before selecting a tool.
            output_token_budget = max(
                output_token_budget,
                MODEL_TRUNCATION_RECOVERY_MIN_TOKENS,
            )
        deadline_options = ({"deadline_monotonic": deadline_monotonic}
                            if deadline_monotonic is not None else {})
        proposal = self.model_client.propose(
            model=self.config.model,
            messages=messages,
            tools=tools,
            temperature=self.config.temperature,
            output_token_budget=output_token_budget,
            enable_thinking=self.config.enable_thinking,
            reasoning_effort=self.config.reasoning_effort,
            reasoning_mode=self.config.reasoning_mode,
            expected_model=self.config.model,
            request_timeout_seconds=request_timeout_seconds,
            **deadline_options,
            presence_penalty=getattr(self.config, "presence_penalty", None),
            thinking_token_budget=getattr(self.config, "thinking_token_budget", None),
            tool_call_stop_sequence=getattr(self.config, "tool_call_stop_sequence", None),
        )
        proposal["_model_visible_tools"] = copy.deepcopy(tools)
        if proposal.get("tool") == "gui_action" and self._latest_gui_coordinate_frame is not None:
            proposal["_gui_coordinate_frame"] = copy.deepcopy(self._latest_gui_coordinate_frame)
        return proposal

    def output_token_budget(self, state: RuntimeState) -> int:
        exposed_names = {tool["function"]["name"] for tool in self.tools(state)}
        semantic_hints = set(
            strict_instruction_required_actions(state.domain, state.instruction)
        )
        generic_matrix_write = bool(
            state.domain == "libreoffice_calc"
            and tool_name("range.write") in exposed_names
            and (
                "range.write" in semantic_hints
                or bool(
                    not semantic_hints.intersection(RANGE_WRITE_FACADES)
                    and re.search(
                        "(?i)\\b(?:write|fill|formula|calculate|compute|enter)\\b",
                        state.instruction,
                    )
                    and re.search(
                        "(?i)\\b(?:table|column|columns|cell|cells|range|values?)\\b",
                        state.instruction,
                    )
                )
            )
        )
        if self._native_pdf_compact_turn(state):
            return min(self.config.max_output_tokens, 2048)
        return (
            max(self.config.max_output_tokens, 2048)
            if generic_matrix_write
            else self.config.max_output_tokens
        )

    def _native_pdf_compact_turn(self, state: RuntimeState) -> bool:
        """Bound deterministic ECS assembly calls to a small tool budget."""
        if getattr(state, "domain", None) != "multi_apps":
            return False
        if not batch_table_semantics.native_pdf_table_observation_complete(state):
            return False
        exposed = {tool["function"]["name"] for tool in self.tools(state)}
        return tool_name("adapter.call") in exposed
