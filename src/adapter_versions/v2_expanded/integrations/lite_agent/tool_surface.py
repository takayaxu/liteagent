"""Extracted LiteAgent support module; keep application semantics generic."""

from __future__ import annotations
import re
from typing import Any
from . import (
    batch_table_semantics,
    calc_semantics,
    clipboard_path_semantics,
    completion_recovery,
    impress_semantics,
    source_execution_semantics,
    spreadsheet_open_semantics,
    verified_artifact_handoff,
    workspace_file_semantics,
    table_ratio_compute,
    pdf_table_selection,
)
from .adapter_results import (
    adapter_context_hint as adapter_context_hint,
    compact_adapter_body as compact_adapter_body,
)
from .completion_policy import (
    action_is_read_only as is_read_only,
    action_is_save as is_save,
    canonical_action_request,
    completion_claim_contradictions as completion_claim_contradictions,
    effective_canonical_action,
)
from .generic_routing import (
    created_workbook_routes,
    discovered_adapter_routes,
    recovery_search_actions,
)
from .local_file_discovery import (
    constrain_failed_path_discovery_tools,
    local_file_discovery_stage_active,
)
from .recovery_alternative import filter_requested_alternative_actions
from .recovery_surface import (
    bounded_recovery_actions,
    decorate_recovery_tools,
    soft_recovery_tools,
)
from .search_recovery_tools import constrain_adapter_call_routes
from .semantic_requirements import strict_semantic_action_equivalents
from .standard_location_semantics import constrain_output_tools
from .tool_catalog import (
    INSPECT_ACTIONS,
    FORBIDDEN_DATASET_ACTIONS,
    build_tools,
    tool_name,
)
from .instruction_semantics import (
    requested_pivot_count,
    requested_title_range_personal_info_cleanup,
    strict_instruction_required_actions,
)
from .impress_title_formatting import (
    constrain_tool_schema as constrain_title_format_tool_schema,
)
from .impress_role_formatting import (
    multislide_visual_title_fallback_plan,
    next_multislide_visual_title_action,
)
from .impress_image_insertion import (
    constrain_image_insertion_tool_schema,
    is_sized_image_insertion_instruction,
)
from .state_model import RuntimeState
from .terminal_tool_constraints import constrain_terminal_provenance_tools
from .filesystem_contexts import (
    ORGANIZATION_SKIP_TOOL_NAME,
    organization_skip_tool,
)
from .organization_validation import current_review_tool


def _filesystem_move_instruction(state: RuntimeState) -> bool:
    """Distinguish filesystem moves from organizing extracted table rows."""
    instruction = str(getattr(state, "instruction", ""))
    table_output = re.search(
        r"(?i)\b(?:in|into)\s+(?:an?\s+)?(?:excel|spreadsheet|table)\b",
        instruction,
    )
    filesystem_mutation = re.search(
        r"(?i)\b(?:files?|folders?|directories|objects?)\b\s+(?:into|to|under)\b|"
        r"\b(?:move|relocate|rename)\b",
        instruction,
    )
    return not (table_output and not filesystem_mutation)


def _latest_explicit_search_routes(state: RuntimeState) -> list[tuple[str, str]]:
    """Return routes from the latest precise or contextual catalog query."""
    events = list(getattr(state, "events", ()) or ())
    if not events:
        return []
    event = events[-1]
    proposed = getattr(event, "proposed", None)
    if not isinstance(proposed, dict) or proposed.get("kind") != "catalog":
        return []
    arguments = proposed.get("arguments")
    query = arguments.get("query") if isinstance(arguments, dict) else None
    if not isinstance(query, str):
        return []
    result = getattr(event, "result", None)
    matches = result.get("matches") if isinstance(result, dict) else None
    routes: list[tuple[str, str]] = []
    if isinstance(matches, list):
        for match in matches:
            if not isinstance(match, dict):
                continue
            adapter = match.get("adapter")
            action = match.get("downstream_action")
            if isinstance(adapter, str) and isinstance(action, str):
                route = (adapter, action)
                if route not in routes:
                    routes.append(route)
    if re.search(
        r"(?<![\w.])(?:[a-z_][\w]*\.)+[a-z_][\w]*(?![\w.])",
        query.casefold(),
    ):
        return routes

    # Public API names can be expressed as words instead of dotted tokens.
    # Match the owning adapter and every action word against actual catalog
    # hits; a broad query such as "read file" still needs normal discovery.
    query_words = set(re.findall(r"[a-z0-9]+", query.casefold()))
    named_routes = [
        (adapter, action) for adapter, action in routes
        if set(re.findall(r"[a-z0-9]+", adapter.casefold())) <= query_words
        and set(re.findall(r"[a-z0-9]+", action.casefold())) <= query_words
    ]
    if len(named_routes) == 1:
        return named_routes

    # Accept a natural-language read request only when the organization state
    # identifies one exact reader for the current object. Unrelated catalog
    # candidates remain search results and are not promoted into the callable
    # surface.
    current_entry = getattr(state, "filesystem_organization_current_entry", None)
    requires_content = getattr(state, "filesystem_organization_requires_content", None)
    read_paths = getattr(state, "filesystem_organization_read_paths", None)
    reader_route = getattr(state, "filesystem_organization_reader_route", None)
    if not all(callable(item) for item in (current_entry, requires_content, read_paths, reader_route)):
        return []
    current = current_entry()
    if current is None or not requires_content(current):
        return []
    current_path = current.get("path") if isinstance(current, dict) else None
    if not isinstance(current_path, str) or current_path in read_paths():
        return []
    query_tokens = set(re.findall(r"[a-z0-9_]+", query.casefold()))
    if not query_tokens.intersection({"read", "open", "inspect", "extract", "text", "content", "pdf"}):
        return []
    route = reader_route(current)
    return [route] if route in routes else []


class ToolSurfaceMixin:
    def _holo_gui_configured(self) -> bool:
        """Return whether GUI turns are delegated to the visual model.

        The attribute checks keep this mixin compatible with small test doubles
        and with the legacy direct-GUI constructor.
        """
        return bool(
            getattr(self, "holo_grounder", None) is not None
            or getattr(self, "holo_gui_gateway", None) is not None
        )

    def _gui_execution_configured(self) -> bool:
        """Return whether direct or delegated GUI execution is available."""
        return bool(
            getattr(self, "gui_executor", None) is not None
            or getattr(self, "holo_gui_gateway", None) is not None
        )

    def _build_tools(
        self,
        domain: str,
        actions: list[str],
        include_gui: bool,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Build a surface using the configured direct or delegated GUI tool."""
        return build_tools(
            domain,
            actions,
            include_gui,
            gui_request=bool(include_gui and self._holo_gui_configured()),
            **kwargs,
        )

    @staticmethod
    def _move_named_tools_to_end(
        tools: list[dict[str, Any]], names: set[str]
    ) -> list[dict[str, Any]]:
        """Keep a fallback action available without making it the attractor."""
        if not names:
            return tools
        retained: list[dict[str, Any]] = []
        moved: list[dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function")
            name = function.get("name") if isinstance(function, dict) else None
            (moved if name in names else retained).append(tool)
        return [*retained, *moved]

    @staticmethod
    def _keep_search_control(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep only the bounded catalog-search control on a consumer retry."""
        terminal_controls = {
            "gui_action",
            "gui_request",
            "propose_done",
            "fail_task",
        }
        return [
            tool
            for tool in tools
            if not isinstance(tool.get("function"), dict)
            or tool["function"].get("name") not in terminal_controls
        ]

    @staticmethod
    def _append_organization_skip_tool(
        tools: list[dict[str, Any]], state: RuntimeState
    ) -> list[dict[str, Any]]:
        """Expose retention only after the current object has been inspected."""
        current = state.filesystem_organization_current_entry()
        if current is None:
            return tools
        check = state.filesystem_organization_check(current)
        if not check or check.get("disposition") != "retain":
            return tools
        if any(
            isinstance(tool.get("function"), dict)
            and tool["function"].get("name") == ORGANIZATION_SKIP_TOOL_NAME
            for tool in tools
        ):
            return tools
        skip = organization_skip_tool()
        skip["function"]["parameters"]["properties"]["path"]["enum"] = [current["path"]]
        insert_at = next(
            (
                index
                for index, tool in enumerate(tools)
                if isinstance(tool.get("function"), dict)
                and tool["function"].get("name") == "tools_search"
            ),
            len(tools),
        )
        return [*tools[:insert_at], skip, *tools[insert_at:]]

    def _filesystem_organization_tools(
        self, state: RuntimeState
    ) -> list[dict[str, Any]] | None:
        """Keep discovery and the current organization mutation recoverable.

        File organization is a state machine, so completion recovery must not
        replace its actionable surface with ``propose_done``/``fail_task``.
        Before discovery, expose catalog search and the exact discovered route.
        After observation, require independent classification before exposing
        the checked rename or retain transition for this source object.
        """
        if (
            not state.filesystem_move_requested()
            or state.filesystem_organization_complete()
        ):
            return None
        # "Organize them in an Excel table" is an output-table request, not a
        # filesystem move workflow.  The source folder wording still makes
        # the broad state predicate true, so keep this distinction at the
        # surface boundary where it controls route exposure.
        if not _filesystem_move_instruction(state):
            return None

        observation = state.filesystem_observation_state()
        route: tuple[str, str] | None = None
        if isinstance(observation, dict) and observation.get("complete") is True:
            current = state.filesystem_organization_current_entry()
            if current is not None:
                if state.filesystem_organization_unverified_move(current):
                    controls = self._build_tools(state.domain, [], include_gui=False, include_control_tools=True, strict_generic=True)
                    return [tool for tool in controls if tool.get("function", {}).get("name") == "fail_task"]
                check = state.filesystem_organization_check(current)
                latest = state.events[-1] if state.events else None
                if latest is not None and not latest.executed and isinstance(latest.error, dict):
                    failed_domain, failed_action, failed_arguments = effective_canonical_action(latest, state.domain)
                    if (
                        (failed_domain, failed_action) == ("os", "filesystem.rename")
                        and failed_arguments.get("source") == current["path"]
                        and latest.error.get("type") in {"ValueError", "RepeatedActionBlocked"}
                    ):
                        retry = current_review_tool(state, current)
                        retry["function"]["description"] += (
                            " The move was rejected before execution. Reconsider "
                            "the current object's classification using the observed "
                            "contents, comparison references and latest validation "
                            "error; a previous passing check does not justify "
                            "repeating a rejected move."
                        )
                        return [retry]
                if check and check.get("disposition") == "retain":
                    skip = organization_skip_tool()
                    skip["function"]["parameters"]["properties"]["path"]["enum"] = [current["path"]]
                    return [skip]
                if check:
                    route = ("os", "filesystem.rename")
                elif state.filesystem_organization_evidence(current) or not state.filesystem_organization_requires_content(current):
                    tools = [current_review_tool(state, current)]
                    latest = state.events[-1].result if state.events else None
                    if isinstance(latest, dict) and (
                        latest.get("evidence_sufficient") is False
                        or tools[0]["function"]["parameters"].get("allOf")
                    ):
                        # Insufficient evidence does not advance the object;
                        # allow a bounded new observation rather than a move.
                        reader = self._build_tools(state.domain, ["adapter.call"], include_gui=False, include_control_tools=False, strict_generic=True)
                        tools.extend(constrain_adapter_call_routes(reader, [state.filesystem_organization_reader_route(current)]))
                    return tools
                else:
                    route = state.filesystem_organization_reader_route(current)
        else:
            discovered = discovered_adapter_routes(state)
            if ("os", "filesystem.find") in discovered:
                route = ("os", "filesystem.find")

        observation_complete = bool(
            isinstance(observation, dict) and observation.get("complete") is True
        )
        current_requires_content = bool(
            observation_complete
            and (current := state.filesystem_organization_current_entry()) is not None
            and state.filesystem_organization_requires_content(current)
        )
        actions = ["adapter.call"] if route is not None else []
        tools = self._build_tools(
            state.domain,
            actions,
            include_gui=False,
            include_control_tools=not current_requires_content,
            strict_generic=True,
        )
        if route is not None:
            tools = constrain_adapter_call_routes(tools, [route])
        tools = self._apply_common_tool_constraints(tools, state)
        if not observation_complete:
            if route is None:
                # Readers cannot be leased until the source inventory exists.
                # Explain that prerequisite even after an unrelated or empty
                # search result instead of silently leaving a search loop.
                tools = [
                    tool for tool in tools
                    if tool.get("function", {}).get("name") == "tools_search"
                ]
                for tool in tools:
                    tool["function"]["description"] += (
                        " File organization requires an observed source inventory "
                        "before content reading or moving. Search for "
                        "os.filesystem.find to discover the inventory tool; "
                        "choose its source roots from the instruction and current "
                        "desktop evidence."
                    )
            else:
                # The inventory route has catalog provenance. Consume it
                # before searching for readers or declaring completion.
                tools = [
                    tool for tool in tools
                    if tool.get("function", {}).get("name") == tool_name("adapter.call")
                ]
                for tool in tools:
                    function = tool["function"]
                    function["description"] += (
                        " Inventory all direct entries in the source directory "
                        "selected from the instruction or desktop evidence. "
                        "When the source files are visible on the desktop, "
                        "use roots=['~/Desktop']. Select the folder containing "
                        "the source objects, not its parent or the entire home. "
                        "Do not filter names: filtered searches can omit source "
                        "objects or comparison references."
                    )
                    params = function["parameters"]["properties"]["payload"]["properties"]["params"]
                    params["properties"]["kind"]["enum"] = ["any"]
                    params["properties"]["name_patterns"] = {
                        "type": "array", "minItems": 1, "maxItems": 1,
                        "items": {"type": "string", "enum": ["*"]},
                    }
                    params["properties"]["recursive"] = {"type": "boolean", "enum": [False]}
                    params["required"] = list(dict.fromkeys([*params["required"], "kind", "recursive"]))
        if route == ("os", "filesystem.find") and observation_complete:
            current = state.filesystem_organization_current_entry()
            if current and current.get("kind") == "directory":
                for tool in tools:
                    if tool.get("function", {}).get("name") != tool_name("adapter.call"):
                        continue
                    function = tool["function"]
                    function["description"] += " Inspect ONLY this current source directory recursively before classification; this does not rediscover or change the source inventory."
                    params = function["parameters"]["properties"]["payload"]["properties"]["params"]
                    params["properties"]["roots"].update({"minItems": 1, "maxItems": 1, "items": {"type": "string", "enum": [current["path"]]}})
                    params["properties"]["name_patterns"] = {
                        "type": "array", "minItems": 1, "maxItems": 1,
                        "items": {"type": "string", "enum": ["*"]},
                    }
                    params["properties"]["kind"]["enum"] = ["any"]
                    params["properties"]["recursive"] = {"type": "boolean", "enum": [True]}
                    params["properties"]["max_depth"].update({"minimum": 1, "maximum": 4})
                    params["properties"]["max_results"].update({"minimum": 1, "maximum": 200})
                    params["required"] = list(dict.fromkeys([*params["required"], "kind", "recursive", "max_depth", "max_results"]))
        if route == ("os", "filesystem.rename"):
            current = state.filesystem_organization_current_entry()
            check = state.filesystem_organization_check(current)
            if current and check:
                for tool in tools:
                    if tool.get("function", {}).get("name") != tool_name("adapter.call"):
                        continue
                    params = tool["function"]["parameters"]["properties"]["payload"]["properties"]["params"]
                    params["properties"]["source"]["enum"] = [current["path"]]
                    params["properties"]["destination"]["enum"] = [
                        check["destination_directory"].rstrip("/") + "/" + current["path"].rsplit("/", 1)[-1]
                    ]
        return self._append_organization_skip_tool(tools, state)

    @staticmethod
    def _recovery_gui_enabled(state: RuntimeState, configured: bool) -> bool:
        """Suppress GUI for a bounded turn after a repeated GUI rejection.

        ``gui_policy`` already records a materially equivalent GUI request as an
        episode/window block.  Keeping the same GUI tool on that immediate
        replan surface invites a small model to emit the same invalid shape
        again, while hiding it for all other failures would remove a legitimate
        fallback.  Adapter routes, ``tools_search``, and terminal controls stay
        available to make the replan explicit and model-selected.
        """
        if not configured:
            return False
        # PDF/image batch-to-table workflows have deterministic public
        # observations and mutations.  GUI fallback only competes with the
        # producer/consumer handoff and can trap a small model in repeated
        # clicks before it discovers the Adapter route.
        if getattr(state, "domain", None) == "multi_apps" and batch_table_semantics.requests_one_record_per_input(
            str(getattr(state, "instruction", ""))
        ):
            batch_failure = any(
                getattr(event, "proposed", {}).get("kind") == "adapter"
                and not getattr(event, "executed", False)
                for event in getattr(state, "events", ())
                if isinstance(getattr(event, "proposed", None), dict)
            )
            if not batch_failure:
                return False
        error = state.events[-1].error if state.events else None
        return not (
            isinstance(error, dict)
            and error.get("type") == "RepeatedActionBlocked"
            and (
                error.get("blocked_action") in {"gui_action", "gui_request"}
                or error.get("fallback_reason") == "repeated_gui_pattern"
            )
        )

    @staticmethod
    def _apply_common_tool_constraints(
        tools: list[dict[str, Any]], state: RuntimeState
    ) -> list[dict[str, Any]]:
        """Apply the same model-facing contracts on every action surface.

        Search and error-recovery are alternate routes into the normal action
        catalog.  They must not silently drop the existing, instruction-local
        schema constraints just because the route was recovered.
        """
        if state.domain == "multi_apps":
            workbook_routes = created_workbook_routes(state)
            if (
                workbook_routes
                and not pdf_table_selection.active(state)
                and not getattr(state, "pending_terminal", None)
                and not _latest_explicit_search_routes(state)
            ):
                # Creating a blank document establishes the editing target.
                # Offer its independent write/save consumers immediately,
                # instead of retaining stale readers and repeated inspection.
                tools = build_tools(
                    state.domain, ["adapter.call"], include_gui=False,
                    include_control_tools=True, strict_generic=True,
                )
                tools = constrain_adapter_call_routes(tools, workbook_routes)
                # Preserve observation-derived write contracts on this
                # early-return surface as well as the normal batch surface.
                for tool in tools:
                    function = tool.get("function", {})
                    if function.get("name") == tool_name("adapter.call"):
                        function["description"] += (
                            " The new workbook is already open; use the worksheet name "
                            "returned by creation. For any cell edit, range.write's "
                            "rectangular range must match "
                            "the number of rows and columns in values exactly. You may "
                            "use the currently listed editing or read-back routes. Save with "
                            "workbook.save_as using your chosen output URL when all "
                            "requested content is complete. These are independent calls; "
                            "creating or writing does not save the workbook."
                        )
                        if ("os", "filesystem.find") in workbook_routes:
                            function["description"] += (
                                " The failed save needs output-parent recovery. Use "
                                "os.filesystem.find with kind=directory to discover "
                                "the requested parent under a model-selected root; "
                                "~/ denotes the active user's home. Use the returned "
                                "absolute directory for your chosen filename; do not "
                                "guess another operating system's home path."
                            )
                        if ("libreoffice_calc", "range.write") not in workbook_routes:
                            function["description"] += (
                                " Persistence was attempted and has not succeeded. "
                                "The successful cell writes remain in the current "
                                "workbook, including after a same-VM restart. A save "
                                "error does not require recreating or rewriting them. "
                                "Discover or correct the output parent, optionally "
                                "read back the existing cells, then retry save_as "
                                "with a corrected URL. To correct observed cell "
                                "content, explicitly search for range.write."
                            )
                        batch_table_semantics.constrain_tool_schema(function, state)
                return soft_recovery_tools(constrain_output_tools(tools, state), state)
            if pdf_table_selection.active(state):
                eligible = pdf_table_selection.allowed_routes(state)
                routes = [route for route in discovered_adapter_routes(state) if route in eligible]
                if routes:
                    tools = constrain_adapter_call_routes(tools, routes)
                else:
                    tools = [item for item in tools if item.get("function", {}).get("name") != tool_name("adapter.call")]
                if not pdf_table_selection.complete(state):
                    tools = [item for item in tools if item.get("function", {}).get("name") not in {"propose_done", "fail_task"}]
                if batch_table_semantics.native_pdf_table_observation_complete(state) and pdf_table_selection.latest_result(state) is None:
                    return [pdf_table_selection.tool(state)]
                hint = pdf_table_selection.stage_hint(state)
                for item in tools:
                    function = item.get("function", {})
                    if function.get("name") in {tool_name("adapter.call"), "tools_search"}:
                        function["description"] = function.get("description", "") + " " + hint
                    if function.get("name") == "tools_search" and eligible:
                        function["parameters"]["properties"]["query"]["enum"] = [
                            f"{adapter}.{action}" for adapter, action in sorted(eligible)
                        ]
                return tools
            explicit_search_routes = _latest_explicit_search_routes(state)
            if explicit_search_routes and state.events[-1].executed:
                # Consume a successful precise search before historical stage
                # filters can hide the very execution route it returned.
                searched_tools = build_tools(
                    state.domain, ["adapter.call"], include_gui=False,
                    include_control_tools=False, strict_generic=True,
                )
                searched_tools = constrain_adapter_call_routes(
                    searched_tools, explicit_search_routes
                )
                return soft_recovery_tools(
                    constrain_output_tools(searched_tools, state), state
                )
            route_pairs = discovered_adapter_routes(state)
            explicit_search_routes = _latest_explicit_search_routes(state)
            if explicit_search_routes:
                # An explicit action query is a precise user/model request.
                # Keep its result intact instead of reapplying a historical
                # batch-stage lease from an earlier search.
                route_pairs = explicit_search_routes
            if state.source_read_target_search_complete():
                # A catalog search after a complete source read may retain
                # historical reader hits. Once it also found a different
                # operation, hide those stale reader routes so the model
                # cannot regress to the already-consumed source phase.
                route_pairs = [
                    (adapter, action)
                    for adapter, action in route_pairs
                    if action not in state._WORKFLOW_READ_ACTIONS
                ]
            structured_source_pending = (
                batch_table_semantics.structured_pdf_source_discovery_pending(state)
            )
            if (
                route_pairs
                and batch_table_semantics.requests_one_record_per_input(
                    str(getattr(state, "instruction", ""))
                )
                and (
                    not state.filesystem_move_requested()
                    or not _filesystem_move_instruction(state)
                )
                and not explicit_search_routes
                and not batch_table_semantics._decimal_rate_matrix_requested(state)
                and batch_table_semantics._latest_successful_batch_event(state)
                is None
                and not structured_source_pending
                and not batch_table_semantics.structured_pdf_table_observation_pending(
                    state
                )
            ):
                # Search results are only candidate routes.  Before the PDF
                # producer has succeeded, expose no consumer route even if a
                # stale search result contains one; keep the producer as the
                # sole executable downstream action.
                route_pairs = [
                    (adapter, action)
                    for adapter, action in route_pairs
                    if action in batch_table_semantics.BATCH_READ_ACTIONS
                ]
            structured_pdf_pending = (
                batch_table_semantics.structured_pdf_table_observation_pending(state)
            )
            if structured_source_pending:
                source_route = ("os", "filesystem.find")
                route_pairs = [source_route] if source_route in route_pairs else []
            elif structured_pdf_pending:
                # A source-complete table task must establish native PDF cell
                # boundaries before any Calc mutation.  Do not infer this
                # route from an unrelated search hit (for example the earlier
                # text-batch reader): until tools_search explicitly returns
                # pdf.tables.inspect, expose only tools_search.
                table_route = ("os", batch_table_semantics.PDF_TABLE_INSPECT_ACTION)
                route_pairs = [table_route] if table_route in route_pairs else []
            elif batch_table_semantics.new_workbook_consumer_pending(state):
                create_route = ("libreoffice_calc", "workbook.create_new")
                route_pairs = [create_route] if create_route in route_pairs else []
            elif route_pairs and (
                batch_table_semantics.requested_fields_complete(state)
                or batch_table_semantics.native_pdf_table_observation_complete(state)
            ):
                route_pairs = [
                    (adapter, action)
                    for adapter, action in route_pairs
                    if batch_table_semantics.batch_route_allowed_after_completion(
                        state, action
                    )
                ]
                # Catalog search commonly returns the create route first.  A
                # source-complete PDF batch still needs one live observation of
                # the already-open Calc workbook before that mutation is
                # eligible.  Add the generic inspection route to the same
                # wrapper schema so the model can choose the required probe
                # without guessing a file path or table range.
                if batch_table_semantics.inspection_pending(state) and (
                    "libreoffice_calc",
                    "workbook.inspect",
                ) in route_pairs:
                    # Before the first live workbook probe, create routes and
                    # catalog search only add another choice. Keep the
                    # zero-argument inspection as the sole next action.
                    route_pairs = [
                        ("libreoffice_calc", "workbook.inspect")
                    ]
                elif not batch_table_semantics.inspection_pending(state):
                    # The active workbook has now been observed.  Prefer the
                    # atomic range mutation for matrix/table consumers and do
                    # not steer an already-open document through create_new.
                    # The next route must still be obtained through the public
                    # tools_search contract before adapter.call can execute.
                    read_done = any(
                        getattr(event, "executed", False)
                        and any(
                            batch_table_semantics._event_matches_action(
                                event, state, candidate
                            )
                            for candidate in (
                                "range.read",
                                "spreadsheet.read_file",
                                "workbook.read_file",
                            )
                        )
                        for event in getattr(state, "events", ())
                    )
                    route_pairs = [
                        (adapter, action)
                        for adapter, action in route_pairs
                        if action not in batch_table_semantics.CREATE_ACTIONS
                        and action not in batch_table_semantics.TARGET_INSPECTION_ACTIONS
                        and (
                            not read_done
                            or action
                            not in {
                                "range.read",
                                "spreadsheet.read_file",
                                "workbook.read_file",
                            }
                        )
                    ]
                    # A successful matrix write starts a strict persistence
                    # handoff.  The catalog search that found the write route
                    # may not have returned Calc read/save, so derive the
                    # next native route from the execution ledger instead of
                    # leaving the model on the completed mutation.
                    post_mutation_route = (
                        batch_table_semantics.next_post_mutation_route(state)
                    )
                    if post_mutation_route is not None:
                        route_pairs = [post_mutation_route]
            # Native ECS matrix workflows must not depend on catalog ranking
            # for the next Calc consumer.  The catalog may return only the
            # incompatible create_new route even though range.read/write are
            # valid atomic actions.  Once the live workbook probe is valid,
            # lease exactly the next consumer action from the event ledger.
            if (
                batch_table_semantics.native_pdf_table_observation_complete(state)
                and batch_table_semantics._valid_target_inspection(state) is not None
                and batch_table_semantics.observed_created_table(state) is None
                and not batch_table_semantics.inspection_pending(state)
            ):
                # A successful write, readback, and save is terminal for this
                # native ECS workflow.  Do not let the generic route fallback
                # below reinterpret the absent post-mutation route as a fresh
                # range.write opportunity.
                if batch_table_semantics.native_pdf_table_workflow_complete(state):
                    completion_tools = build_tools(
                        state.domain,
                        [],
                        include_gui=False,
                        include_control_tools=True,
                        strict_generic=True,
                    )
                    completion_tools = [
                        tool
                        for tool in completion_tools
                        if isinstance(tool.get("function"), dict)
                        and tool["function"].get("name") == "propose_done"
                    ]
                    return completion_tools
                next_route = batch_table_semantics.next_post_mutation_route(state)
                route_pairs = [
                    next_route
                    if next_route is not None
                    else (
                        "libreoffice_calc",
                        "range.write"
                        if table_ratio_compute.latest_result(state) is not None
                        else "range.read",
                    )
                ]
            adapter_call_name = tool_name("adapter.call")
            organization_observation = state.filesystem_observation_state()
            if isinstance(organization_observation, dict) and organization_observation.get(
                "complete"
            ) is True:
                # Organization is a single-object state machine.  Only the
                # current object's reader (when ambiguous) or its exact move
                # route is exposed; the next object is hidden until this one
                # has been classified and moved.
                current = state.filesystem_organization_current_entry()
                if current is not None:
                    check = state.filesystem_organization_check(current)
                    if check and check.get("disposition") == "retain":
                        route_pairs = []
                    elif check and check.get("disposition") == "move":
                        route_pairs = [("os", "filesystem.rename")]
                    else:
                        route_pairs = [state.filesystem_organization_reader_route(current)]
                else:
                    route_pairs = []
            if route_pairs:
                tools = constrain_adapter_call_routes(tools, route_pairs)
                if (
                    route_pairs == [("libreoffice_calc", "range.read")]
                    and batch_table_semantics.native_pdf_table_observation_complete(state)
                    and table_ratio_compute.target_layout(state) is None
                ):
                    target = table_ratio_compute.target_read_request(state)
                    if target is not None:
                        for candidate in tools:
                            function = candidate.get("function")
                            if not isinstance(function, dict) or function.get("name") != adapter_call_name:
                                continue
                            params = function["parameters"]["properties"]["payload"]["properties"]["params"]
                            params["properties"]["sheet"]["enum"] = [target["sheet"]]
                            params["properties"]["range"]["enum"] = [target["range"]]
                            function["description"] += (
                                " Read the complete observed header and year rectangle once "
                                "to bind the next ratio computation to worksheet row and column keys."
                            )
            else:
                tools = [
                    tool
                    for tool in tools
                    if not isinstance(tool.get("function"), dict)
                    or tool["function"].get("name") != adapter_call_name
                ]
            observation = state.filesystem_observation_state()
            if isinstance(observation, dict) and observation.get("complete") is True:
                for tool in tools:
                    function = tool.get("function")
                    if not isinstance(function, dict) or function.get("name") != adapter_call_name:
                        continue
                    function["description"] = (
                        str(function.get("description", ""))
                        + " Filesystem observation is complete: classify the exact observed "
                        "entries and move them with filesystem.rename; do not call "
                        "filesystem.find again for an observed root. Read content only "
                        "when a file remains ambiguous."
                    )
                    current = state.filesystem_organization_current_entry()
                    if current is not None and state.filesystem_organization_requires_content(current):
                        current_path = current.get("path")
                        if isinstance(current_path, str) and current_path:
                            function["description"] += (
                                " For organization, read exactly the current object using this "
                                f"exact normalized absolute path: {current_path}. Put that "
                                "full path in the route's path, input_path, file_path, or "
                                "input_pattern field as applicable; basenames and wildcard "
                                "patterns are forbidden and will be rejected."
                            )
                    function["description"] += (
                        " Organization progress is authoritative and only tracks the current "
                        "object: use its exact current_object path, and do not advance until "
                        "the object is classified and either moved or explicitly skipped. "
                        "After completion, the marker is "
                        "reset for the next current object; never repeat a completed path."
                    )
                # Once the exact rename route is discovered, another catalog
                # search adds no evidence and can trap small models in a loop.
                # Keep the correlated adapter route for the mutation phase.
                if (
                    any(route == ("os", "filesystem.rename") for route in route_pairs)
                    and not (
                        state.filesystem_move_requested()
                        and not state.filesystem_organization_complete()
                    )
                ):
                    tools = [
                        tool
                        for tool in tools
                        if not isinstance(tool.get("function"), dict)
                        or tool["function"].get("name") != "tools_search"
                    ]
            # Once catalog search has found the required native PDF table
            # route, expose its execution API directly.  Leaving
            # ``tools_search`` beside the exact route lets a small model keep
            # searching forever instead of consuming the returned route.
            table_route_ready = (
                structured_pdf_pending
                and ("os", batch_table_semantics.PDF_TABLE_INSPECT_ACTION)
                in route_pairs
            )
            source_route_ready = (
                structured_source_pending
                and ("os", "filesystem.find") in route_pairs
            )
            if table_route_ready or source_route_ready:
                if not any(
                    isinstance(tool.get("function"), dict)
                    and tool["function"].get("name") == adapter_call_name
                    for tool in tools
                ):
                    tools.extend(
                        build_tools(
                            state.domain,
                            ["adapter.call"],
                            include_gui=False,
                            include_control_tools=False,
                            strict_generic=True,
                        )
                    )
                    tools = constrain_adapter_call_routes(tools, route_pairs)
                tools = [
                    tool
                    for tool in tools
                    if not isinstance(tool.get("function"), dict)
                    or tool["function"].get("name") == adapter_call_name
                ]
            return soft_recovery_tools(tools, state)
        if spreadsheet_open_semantics.gui_request_contract_errors(state):
            tools = [
                tool
                for tool in tools
                if not isinstance(tool.get("function"), dict)
                or tool["function"].get("name") not in {"gui_action", "gui_request"}
            ]
        for tool in tools:
            function = tool.get("function")
            if not isinstance(function, dict):
                continue
            picture_height_step = impress_semantics.next_picture_height_action(state)
            if (
                picture_height_step is not None
                and picture_height_step["action"] == "shape.set_geometry"
            ):
                impress_semantics.constrain_tool_schema(function, state)
            batch_table_semantics.constrain_tool_schema(function, state)
            calc_semantics.constrain_sort_tool_schema(function, state)
            calc_semantics.constrain_stacked_aggregate_tool_schema(
                function,
                state.instruction,
                requested_pivot_count(state.instruction),
            )
            constrain_title_format_tool_schema(function, state.instruction)
            constrain_image_insertion_tool_schema(function, state)
            verified_artifact_handoff.constrain_tool_schema(function, state)
        constrained = constrain_failed_path_discovery_tools(
            constrain_output_tools(
                constrain_terminal_provenance_tools(tools, state.instruction),
                state,
            ),
            state,
        )
        return soft_recovery_tools(constrained, state)

    def tools(self, state: RuntimeState) -> list[dict[str, Any]]:
        multi_app = state.domain == "multi_apps"
        batch_workflow = multi_app and (
            batch_table_semantics.requests_one_record_per_input(
                str(getattr(state, "instruction", ""))
            )
            or batch_table_semantics._decimal_rate_matrix_requested(state)
        )
        has_successful_batch = multi_app and any(
            state.successful_action_events(action)
            for action in batch_table_semantics.BATCH_READ_ACTIONS
        )
        # Only the latest unexecuted Adapter event is an active batch failure.
        # An earlier provenance/schema failure is recovered once a later
        # search or Adapter call succeeds; keeping historical failures sticky
        # reopens the generic GUI recovery surface after observation completes.
        latest_event = state.events[-1] if state.events else None
        latest_proposed = getattr(latest_event, "proposed", None)
        batch_failure = bool(
            batch_workflow
            and isinstance(latest_proposed, dict)
            and latest_proposed.get("kind") == "adapter"
            and not getattr(latest_event, "executed", False)
        )
        batch_observation_gate = bool(
            multi_app
            and (
                batch_table_semantics.requested_fields_complete(state)
                or batch_table_semantics.structured_pdf_table_observation_pending(
                    state
                )
                or batch_table_semantics.native_pdf_table_observation_complete(state)
            )
        )
        pending_terminal = getattr(state, "pending_terminal", None)
        if isinstance(pending_terminal, dict):
            expected_tool = str(pending_terminal.get("tool", "propose_done"))
            if expected_tool not in {"propose_done", "fail_task"}:
                expected_tool = "propose_done"
            audit_tools = completion_recovery.completion_review_tools(state, self.selected_actions(state))
            audit_tools = self._apply_common_tool_constraints(audit_tools, state)
            for tool in audit_tools:
                function = tool.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if name in {"propose_done", "fail_task"}:
                    function["description"] = (
                        f"Confirm the previous {expected_tool} result only if every required outcome holds. "
                        "If work remains, choose an exposed inspection or repair action to reopen execution."
                    )
            return audit_tools

        # Native result defects outrank phase/ranking filters, which can hide
        # the very read or mutation needed to repair an already executed call.
        outcome_tools = completion_recovery.outcome_recovery_tools(
            state, self._generic_completion_gate(state)
        )
        if outcome_tools is not None:
            return outcome_tools

        if pdf_table_selection.active(state):
            tools = self._build_tools(state.domain, ["adapter.call"], include_gui=False, include_control_tools=True, strict_generic=True)
            return self._apply_common_tool_constraints(tools, state)


        if (
            state.domain == "multi_apps"
            and batch_table_semantics.native_pdf_table_observation_complete(state)
            and batch_table_semantics._valid_target_inspection(state) is not None
            and table_ratio_compute.target_layout(state) is not None
            and batch_table_semantics.observed_created_table(state) is None
            and not batch_table_semantics.native_pdf_table_workflow_complete(state)
            and table_ratio_compute.latest_result(state) is None
        ):
            return [table_ratio_compute.tool(state)]

        organization_tools = self._filesystem_organization_tools(state)
        if organization_tools is not None:
            return organization_tools

        # A complete source read is a durable phase boundary.  For a
        # multi-application instruction that still contains an operation verb,
        # expose the catalog control as the only next action so the model must
        # discover the owning application's mutation API (for example a mail
        # recipient writer) instead of replaying the source reader.
        if state.source_read_handoff_pending():
            handoff_tools = self._build_tools(
                state.domain,
                [],
                include_gui=False,
                include_control_tools=True,
                strict_generic=True,
            )
            handoff_tools = [
                tool
                for tool in handoff_tools
                if isinstance(tool.get("function"), dict)
                and tool["function"].get("name") == "tools_search"
            ]
            for tool in handoff_tools:
                function = tool.get("function")
                if isinstance(function, dict):
                    description = str(function.get("description", "")) + (
                        " The source file has already been found, opened, and read "
                        "successfully. Its observed contents are retained in "
                        "workflow_progress. Do not reread it; search for the next "
                        "requested application action or mutation."
                    )
                    if state.requested_mail_recipient_target():
                        description += (
                            " This is a mail-recipient write task. Search exactly one "
                            "of the public target routes: "
                            "thunderbird.compose.set_recipients or "
                            "mail.compose_recipients. Do not search Calc or other "
                            "spreadsheet read/write routes."
                        )
                    function["description"] = description
            return handoff_tools

        clipboard_stage = (
            None if multi_app else clipboard_path_semantics.pending_actions(state)
        )
        if clipboard_stage is not None:
            terminal_only = not clipboard_stage
            tools = self._build_tools(
                state.domain,
                clipboard_stage,
                include_gui=False,
                include_control_tools=terminal_only,
                strict_generic=True,
            )
            if terminal_only:
                tools = [
                    tool
                    for tool in tools
                    if not isinstance(tool.get("function"), dict)
                    or tool["function"].get("name") != "tools_search"
                ]
            return self._apply_common_tool_constraints(tools, state)

        spreadsheet_open_stage = (
            None if multi_app else spreadsheet_open_semantics.pending_actions(state)
        )
        if spreadsheet_open_stage is not None:
            tools = self._build_tools(
                state.domain,
                spreadsheet_open_stage,
                include_gui=False,
                include_control_tools=False,
                strict_generic=True,
            )
            return self._apply_common_tool_constraints(tools, state)

        strict_required_actions = [
            action
            for action in strict_instruction_required_actions(
                state.domain, state.instruction
            )
            if action not in FORBIDDEN_DATASET_ACTIONS
        ]
        required_mutations = [
            action
            for action in strict_required_actions
            if not is_read_only(action) and (not is_save(action))
        ]
        attempted_action_ids = {
            effective_canonical_action(event, state.domain)[:2]
            for event in state.events
            if event.executed and event.proposed.get("kind") == "adapter"
        }
        untried_required_mutations = [
            action
            for action in required_mutations
            if canonical_action_request(state.domain, action, {})[:2]
            not in attempted_action_ids
        ]
        phase_tools = (
            [] if multi_app else source_execution_semantics.build_phase_tools(state)
        )
        consumer_recovery_actions = (
            None
            if multi_app
            else batch_table_semantics.pending_consumer_recovery_actions(
                state, self.selected_actions(state)
            )
        )
        if consumer_recovery_actions:
            # A failed read-only consumer leaves the observed target unchanged.
            # Keep the model on the bounded consumer surface while preserving
            # model-authored arguments.  A pre-mutation write contract error
            # also gets one bounded catalog-search control so the model can
            # discover a reusable route/schema before choosing its next call.
            allow_search = batch_table_semantics.consumer_recovery_allows_search(state)
            consumer_recovery_tools = self._build_tools(
                state.domain,
                list(consumer_recovery_actions),
                include_gui=False,
                include_control_tools=allow_search,
                strict_generic=True,
            )
            if allow_search:
                consumer_recovery_tools = self._keep_search_control(
                    consumer_recovery_tools
                )
            consumer_recovery_tools = self._apply_common_tool_constraints(
                consumer_recovery_tools, state
            )
            continuation_names = {
                tool_name(action)
                for action in consumer_recovery_actions
                if action in batch_table_semantics.BATCH_READ_ACTIONS
            }
            return self._move_named_tools_to_end(
                consumer_recovery_tools, continuation_names
            )
        producer_actions = (
            None
            if multi_app
            else batch_table_semantics.pending_producer_actions(
                state, self.selected_actions(state)
            )
        )
        if producer_actions:
            # A batch workflow must establish its source records before GUI
            # fallback or completion controls compete for the first action.
            # The model still supplies every producer argument unchanged.
            producer_tools = self._build_tools(
                state.domain,
                list(producer_actions),
                include_gui=False,
                include_control_tools=False,
                strict_generic=True,
            )
            return self._apply_common_tool_constraints(producer_tools, state)
        # A rejected completion claim is a bounded recovery transition.  Run
        # this surface before repeated-action/replan handling so a missing
        # persistence step cannot send the model back to the successful write
        # or to an unconstrained GUI fallback.  The phase helper itself still
        # requires real mutation evidence and save/read-back-only obligations.
        if getattr(state, "completion_rejections", 0) > 0:
            proactive_tools = completion_recovery.strict_proactive_completion_tools(
                state,
                self._generic_completion_gate(state),
                strict_instruction_required_actions,
                FORBIDDEN_DATASET_ACTIONS,
                is_read_only,
                self.selected_actions,
                strict_semantic_action_equivalents,
            )
            if proactive_tools:
                return self._apply_common_tool_constraints(proactive_tools, state)
        recovery_actions = recovery_search_actions(state)
        if recovery_actions is not None and not batch_observation_gate:
            recovery_actions = filter_requested_alternative_actions(
                state, recovery_actions
            )
            recovery_actions = bounded_recovery_actions(
                state,
                required_actions=untried_required_mutations,
                searched_actions=recovery_actions,
                selected_actions=self.selected_actions(state),
                limit=max(1, self.config.top_k_actions),
            )
            # A failed required mutation is precisely when a GUI fallback may
            # be useful; keeping it visible does not choose the route.
            recovery_tools = self._build_tools(
                state.domain,
                recovery_actions,
                include_gui=self._recovery_gui_enabled(
                    state,
                    self.config.include_gui and self._gui_execution_configured(),
                ),
                include_control_tools=True,
                strict_generic=True,
            )
            return decorate_recovery_tools(
                self._apply_common_tool_constraints(recovery_tools, state),
                state,
                mode="catalog_search",
            )
        if (
            (state.requires_replan() or state.active_request_blocks())
            and not batch_observation_gate
        ):
            recovery_actions = bounded_recovery_actions(
                state,
                required_actions=untried_required_mutations,
                searched_actions=list(getattr(state, "expanded_actions", ()))[-4:],
                selected_actions=self.selected_actions(state),
                limit=max(1, self.config.top_k_actions),
            )
            tools = self._build_tools(
                state.domain,
                recovery_actions,
                include_gui=self._recovery_gui_enabled(
                    state,
                    self.config.include_gui and self._gui_execution_configured(),
                ),
                include_control_tools=True,
                strict_generic=True,
            )
            blocked = list(state.active_request_blocks().values())
            if blocked:
                blocked_action_count = len(
                    {item.get("action") for item in blocked if item.get("action")}
                )
                fully_blocked_count = len(state.blocked_actions())
                for tool in tools:
                    function = tool.get("function")
                    if (
                        isinstance(function, dict)
                        and function.get("name") == "tools_search"
                    ):
                        function["description"] += (
                            f" {blocked_action_count} exact request variant(s) are temporarily blocked; "
                            f"{fully_blocked_count} public action(s) have no remaining read variant. "
                            "Choose a different public action or materially different arguments."
                        )
                        break
            return decorate_recovery_tools(
                self._apply_common_tool_constraints(tools, state),
                state,
                mode="replan",
            )
        consumer_actions = (
            None
            if multi_app
            else batch_table_semantics.pending_consumer_actions(
                state, self.selected_actions(state)
            )
        )
        if consumer_actions:
            # Keep the post-inspection handoff small until the model selects a
            # real downstream operation.  Errors still fall through to the
            # normal recovery surface above.
            consumer_tools = self._build_tools(
                state.domain,
                list(consumer_actions),
                include_gui=False,
                include_control_tools=False,
                strict_generic=True,
            )
            return self._apply_common_tool_constraints(consumer_tools, state)
        post_mutation_actions = (
            None
            if multi_app
            else batch_table_semantics.pending_post_mutation_actions(
                state, self.selected_actions(state)
            )
        )
        if post_mutation_actions:
            # After a batch consumer mutation, verify and persist it before
            # exposing unrelated GUI or terminal fallbacks.
            post_mutation_tools = self._build_tools(
                state.domain,
                list(post_mutation_actions),
                include_gui=False,
                include_control_tools=False,
                strict_generic=True,
            )
            return self._apply_common_tool_constraints(post_mutation_tools, state)
        proactive_tools = completion_recovery.strict_proactive_completion_tools(
            state,
            self._generic_completion_gate(state),
            strict_instruction_required_actions,
            FORBIDDEN_DATASET_ACTIONS,
            is_read_only,
            self.selected_actions,
            strict_semantic_action_equivalents,
        )
        if proactive_tools and not (
            multi_app and batch_table_semantics.requested_fields_complete(state)
        ):
            return self._apply_common_tool_constraints(proactive_tools, state)
        if (
            multi_app
            and batch_observation_gate
        ):
            # Once every source PDF has been observed, suppress GUI and
            # filesystem recovery.  Keep only the deterministic adapter route
            # (or catalog search when the consumer route has not been found).
            batch_tools = self._build_tools(
                state.domain,
                ["adapter.call"],
                include_gui=False,
                include_control_tools=True,
                strict_generic=True,
            )
            batch_tools = self._apply_common_tool_constraints(batch_tools, state)
            if not batch_table_semantics.mutation_and_save_complete(state):
                # A source-complete batch is authoritative structured evidence.
                # Do not let screenshot state or a stale GUI hypothesis abort
                # the workflow before its model-selected table mutation and
                # persistence have run.
                batch_tools = [
                    tool
                    for tool in batch_tools
                    if not isinstance(tool.get("function"), dict)
                    or tool["function"].get("name")
                    not in {"propose_done", "fail_task"}
                ]
            if batch_table_semantics.inspection_pending(state):
                batch_tools = [
                    tool
                    for tool in batch_tools
                    if not isinstance(tool.get("function"), dict)
                    or tool["function"].get("name") in {"adapter__adapter_call", "tools_search"}
                ]
                if batch_failure and not any(
                    isinstance(tool.get("function"), dict)
                    and tool["function"].get("name") == "tools_search"
                    for tool in batch_tools
                ):
                    # A rejected adapter route needs a fresh catalog lookup;
                    # retaining only the failed adapter schema traps small
                    # models in the same unexecutable call.
                    search_tools = self._build_tools(
                        state.domain,
                        [],
                        include_gui=False,
                        include_control_tools=True,
                        strict_generic=True,
                    )
                    batch_tools.extend(
                        tool
                        for tool in search_tools
                        if isinstance(tool.get("function"), dict)
                        and tool["function"].get("name") == "tools_search"
                    )
                if (
                    any(
                        isinstance(tool.get("function"), dict)
                        and tool["function"].get("name") == "adapter__adapter_call"
                        for tool in batch_tools
                    )
                    and not batch_failure
                ):
                    batch_tools = [
                        tool
                        for tool in batch_tools
                        if not isinstance(tool.get("function"), dict)
                        or tool["function"].get("name") != "tools_search"
                    ]
            else:
                # A successful search already supplied an executable consumer
                # route.  Remove the catalog control so the model cannot keep
                # searching instead of issuing that observation/mutation.
                consumer_routes = {
                    action
                    for _, action in discovered_adapter_routes(state)
                    if action
                    in {
                        "range.read",
                        "range.write",
                        "spreadsheet.read_file",
                        "spreadsheet.write_range",
                        "workbook.read_file",
                        "workbook.create_new",
                    }
                }
                if consumer_routes:
                    batch_tools = [
                        tool
                        for tool in batch_tools
                        if not isinstance(tool.get("function"), dict)
                        or tool["function"].get("name") != "tools_search"
                    ]
            if (
                batch_table_semantics.native_pdf_table_observation_complete(state)
                and batch_table_semantics._valid_target_inspection(state) is not None
                and batch_table_semantics.observed_created_table(state) is None
                and not batch_table_semantics.inspection_pending(state)
                and any(
                    isinstance(tool.get("function"), dict)
                    and tool["function"].get("name") == tool_name("adapter.call")
                    for tool in batch_tools
                )
            ):
                # Search is no longer a valid next step after native source
                # completion and a successful target probe.
                batch_tools = [
                    tool
                    for tool in batch_tools
                    if not isinstance(tool.get("function"), dict)
                    or tool["function"].get("name") == tool_name("adapter.call")
                ]
            # The structured-result gate must never produce an empty tool
            # array: Qwen rejects ``tools=[]`` before the model can search for
            # the next Calc mutation route. Keep catalog search as the sole
            # recovery action when route filtering removed every Adapter call.
            if not any(
                isinstance(tool.get("function"), dict)
                for tool in batch_tools
            ):
                search_tools = self._build_tools(
                    state.domain,
                    [],
                    include_gui=False,
                    include_control_tools=True,
                    strict_generic=True,
                )
                batch_tools = [
                    tool
                    for tool in search_tools
                    if isinstance(tool.get("function"), dict)
                    and tool["function"].get("name") == "tools_search"
                ]
            # After the write/readback handoff, the route schema intentionally
            # contains only workbook.save.  State that terminal lease in the
            # tool description so a model cannot reopen a stale PDF hypothesis
            # when the latest readback window omits a row label.
            if (
                len(
                    [
                        tool
                        for tool in batch_tools
                        if isinstance(tool.get("function"), dict)
                    ]
                )
                == 1
                and any(
                    isinstance(tool.get("function"), dict)
                    and tool["function"].get("name") == tool_name("adapter.call")
                    for tool in batch_tools
                )
                and batch_table_semantics.next_post_mutation_route(state)
                == ("libreoffice_calc", "workbook.save")
            ):
                for tool in batch_tools:
                    function = tool.get("function")
                    if isinstance(function, dict) and function.get("name") == tool_name(
                        "adapter.call"
                    ):
                        function["description"] = (
                            str(function.get("description", ""))
                            + " The mutation and readback are complete. The only valid "
                            "next action is libreoffice_calc.workbook.save; do not "
                            "re-read any PDF, call range.read, or search for another route."
                        )
            # This stage narrows the route after the common constraints ran.
            # Bind the final payload schema to the next observed write row.
            for tool in batch_tools:
                function = tool.get("function")
                if isinstance(function, dict):
                    batch_table_semantics.constrain_tool_schema(function, state)
            return batch_tools
        organization_observation = state.filesystem_observation_state()
        if isinstance(organization_observation, dict) and organization_observation.get(
            "complete"
        ) is True:
            if state.filesystem_organization_complete():
                completion_tools = self._build_tools(
                    state.domain,
                    [],
                    include_gui=False,
                    include_control_tools=True,
                    strict_generic=True,
                )
                completion_tools = [
                    tool
                    for tool in completion_tools
                    if isinstance(tool.get("function"), dict)
                    and tool["function"].get("name") == "propose_done"
                ]
                return self._apply_common_tool_constraints(completion_tools, state)
            current = state.filesystem_organization_current_entry()
            if current is None:
                return self._build_tools(
                    state.domain, [], include_gui=False, include_control_tools=True, strict_generic=True
                )
            # Do not retain a separate read->mutation shortcut here.
            organization_tools = self._filesystem_organization_tools(state)
            if organization_tools is not None:
                return organization_tools
        visual_title_plan = multislide_visual_title_fallback_plan(state)
        if visual_title_plan is not None and next_multislide_visual_title_action(state) is None:
            saves = state.successful_action_events("presentation.save")
            if saves and any(
                event.step > saves[-1].step
                and event.proposed.get("action") == "presentation.inspect"
                and event.executed
                for event in state.events
            ):
                completion_tools = self._build_tools(
                    state.domain,
                    [],
                    include_gui=False,
                    include_control_tools=True,
                    strict_generic=True,
                )
                return [
                    tool
                    for tool in completion_tools
                    if isinstance(tool.get("function"), dict)
                    and tool["function"].get("name") == "propose_done"
                ]
        if phase_tools:
            return self._apply_common_tool_constraints(phase_tools, state)
        actions = calc_semantics.stage_new_sheet_prerequisites(
            state, self.selected_actions(state), strict_required_actions
        )
        if (
            state.domain == "libreoffice_impress"
            and not actions
            and impress_semantics.final_readback_complete(state)
        ):
            completion_tools = self._build_tools(
                state.domain,
                [],
                include_gui=False,
                include_control_tools=True,
                strict_generic=True,
            )
            return [
                tool
                for tool in completion_tools
                if isinstance(tool.get("function"), dict)
                and tool["function"].get("name") == "propose_done"
            ]
        cleanup_request = requested_title_range_personal_info_cleanup(state.instruction)
        cleanup_in_progress = bool(
            cleanup_request is not None
            and state.next_title_range_personal_info_cleanup_action() is not None
        )
        visual_title_fallback_in_progress = bool(
            multislide_visual_title_fallback_plan(state) is not None
            and next_multislide_visual_title_action(state) is not None
        )
        terminal_only = tuple(actions) in {("propose_done",), ("fail_task",)}
        batch_inspection_pending = (
            False if multi_app else batch_table_semantics.inspection_pending(state)
        )
        if batch_inspection_pending:
            # A successful producer does not establish which application
            # object is the consumer.  Force the model to make the generic
            # zero-argument probe before GUI or terminal controls compete for
            # the next turn.  The probe result remains model-visible and all
            # later mutation arguments are still model-selected.
            actions = [batch_table_semantics.INSPECT_ACTION]
        discovery_only = bool(
            not state.events
            and len(actions) == 1
            and (actions[0] in INSPECT_ACTIONS.get(state.domain, ()))
        ) or local_file_discovery_stage_active(state, actions)
        # The physical-image route exposes its mutation schema on the first
        # turn so the model cannot conclude that the action is unavailable,
        # while retaining the discovery-only control surface (no search,
        # GUI, or terminal completion choices) and ordered inspection first.
        discovery_only = discovery_only or (
            not state.events
            and state.domain == "libreoffice_impress"
            and is_sized_image_insertion_instruction(str(state.instruction))
            and actions[:2] == ["presentation.inspect", "shape.insert_image"]
        )
        # After a successful image insertion, the owning stage deliberately
        # exposes only the next persistence/read-back action.  Keep the same
        # narrow surface free of search, GUI, and terminal controls so a small
        # model cannot bypass that existing sequence or propose completion
        # before its evidence is present.
        discovery_only = discovery_only or (
            state.domain == "libreoffice_impress"
            and is_sized_image_insertion_instruction(str(state.instruction))
            and state.successful_action_events("shape.insert_image")
            and actions in (["presentation.save"], ["presentation.inspect"])
        )
        discovery_only = discovery_only or batch_inspection_pending
        # Composite Impress mutations have a strict one-action handoff. Once
        # action selection narrows the stage to one of these actions, hide
        # GUI/search/completion bypasses so the model performs that action and
        # advances to the next observation-derived stage.
        discovery_only = discovery_only or (
            state.domain == "libreoffice_impress"
            and tuple(actions)
            in {
                ("presentation.inspect",),
                ("shape.set_geometry",),
                ("slide.format_text_roles",),
                ("presentation.save",),
            }
        )
        # Composite Impress cleanup is an ordered mutation plan. Until its
        # final mutation succeeds, expose only the current next mutation and
        # suppress save, completion, search, and GUI controls.
        discovery_only = discovery_only or cleanup_in_progress
        discovery_only = discovery_only or visual_title_fallback_in_progress
        if not multi_app:
            discovery_only = discovery_only or workspace_file_semantics.stage_active(
                state, actions
            )
        tools = self._build_tools(
            state.domain,
            actions,
            include_gui=self.config.include_gui
            and self._gui_execution_configured()
            and not terminal_only
            and not batch_observation_gate
            and (not discovery_only)
            and (not untried_required_mutations),
            include_control_tools=not discovery_only,
            strict_generic=True,
        )
        # The cleanup completion gate needs one read-back containing both
        # formatted title slides and the cleaned personal-information slide.
        # A generic inspect schema lets a model repeatedly inspect only the
        # already-verified title pages, so constrain this single final probe to
        # the exact pages represented by the immutable cleanup plan.
        if (
            cleanup_request is not None
            and tuple(actions) == ("presentation.inspect",)
            and not state.title_range_personal_info_cleanup_readback_satisfied()
        ):
            cleanup_plan = state.title_range_personal_info_cleanup_plan()
            if isinstance(cleanup_plan, dict):
                planned_events = [
                    event
                    for step in cleanup_plan["steps"]
                    for event in state.successful_action_events(step["action"])
                    if event.proposed.get("arguments") == step["arguments"]
                ]
                last_mutation = max(
                    (event.step for event in planned_events), default=-1
                )
                saved_after_mutation = any(
                    is_save(str(event.proposed.get("action", "")))
                    and event.step > last_mutation
                    for event in state.successful_adapter_events()
                )
                if saved_after_mutation:
                    required_slides = sorted(
                        {
                            *(
                                int(target["slide"])
                                for target in cleanup_plan["title_paths"]
                            ),
                            int(cleanup_plan["cleanup_slide"]),
                        }
                    )
                    for tool in tools:
                        function = tool.get("function")
                        if not isinstance(function, dict) or function.get(
                            "name"
                        ) != tool_name("presentation.inspect"):
                            continue
                        function["description"] = (
                            "Final cleanup read-back. Inspect exactly these slide "
                            f"indices: {required_slides}."
                        )
                        function["parameters"] = {
                            "type": "object",
                            "properties": {
                                "slides": {
                                    "type": "array",
                                    "const": required_slides,
                                    "items": {"type": "integer"},
                                }
                            },
                            "required": ["slides"],
                            "additionalProperties": False,
                        }
        tools = self._apply_common_tool_constraints(tools, state)
        if terminal_only:
            tools = [
                tool
                for tool in tools
                if isinstance(tool.get("function"), dict)
                and tool["function"].get("name") == actions[0]
            ]
        if (
            has_successful_batch
            and not batch_table_semantics.mutation_and_save_complete(state)
        ):
            # A successful source read is not a completed task.  Keep the
            # terminal control hidden until the table mutation and persistence
            # have both succeeded, even on the generic action surface.
            tools = [
                tool
                for tool in tools
                if not isinstance(tool.get("function"), dict)
                or tool["function"].get("name") != "propose_done"
            ]
        return tools
