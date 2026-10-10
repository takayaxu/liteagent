"""Extracted LiteAgent support module; keep application semantics generic."""

from __future__ import annotations
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
from .generic_routing import discovered_adapter_routes, recovery_search_actions
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
            route_pairs = discovered_adapter_routes(state)
            structured_source_pending = (
                batch_table_semantics.structured_pdf_source_discovery_pending(state)
            )
            if (
                route_pairs
                and batch_table_semantics.requests_one_record_per_input(
                    str(getattr(state, "instruction", ""))
                )
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
                if (
                    batch_table_semantics.inspection_pending(state)
                    and ("libreoffice_calc", "workbook.inspect") not in route_pairs
                ):
                    route_pairs.insert(0, ("libreoffice_calc", "workbook.inspect"))
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
                next_route = batch_table_semantics.next_post_mutation_route(state)
                route_pairs = [
                    next_route
                    if next_route is not None
                    else (
                        "libreoffice_calc",
                        "range.write" if read_done else "range.read",
                    )
                ]
            adapter_call_name = tool_name("adapter.call")
            organization_observation = state.filesystem_observation_state()
            if isinstance(organization_observation, dict) and organization_observation.get(
                "complete"
            ) is True:
                # Once discovery is complete, the only downstream mutation
                # permitted on this surface is the observed rename operation.
                if any(action == "filesystem.rename" for _, action in route_pairs):
                    route_pairs = [
                        (adapter, action)
                        for adapter, action in route_pairs
                        if action == "filesystem.rename"
                    ]
            if route_pairs:
                tools = constrain_adapter_call_routes(tools, route_pairs)
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
            # A passed terminal result has no remaining mutation to plan. Keep
            # its single audit turn deterministic: exposing search and action
            # alternatives lets a model reopen a completed episode indefinitely.
            expected_tool = str(pending_terminal.get("tool", "propose_done"))
            if expected_tool not in {"propose_done", "fail_task"}:
                expected_tool = "propose_done"
            audit_tools = self._build_tools(
                state.domain,
                [],
                include_gui=False,
                include_control_tools=True,
                strict_generic=True,
            )
            audit_tools = [
                tool
                for tool in audit_tools
                if isinstance(tool.get("function"), dict)
                and tool["function"].get("name") == expected_tool
            ]
            audit_tools = self._apply_common_tool_constraints(audit_tools, state)
            for tool in audit_tools:
                function = tool.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if name in {"propose_done", "fail_task"}:
                    function["description"] = (
                        f"Confirm the previous {expected_tool} result once. "
                        "The result was already accepted and no further action is needed."
                    )
            return audit_tools

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
            # The initial discovery search usually returns only the find route.
            # Force one catalog lookup for the mutation route instead of leaving
            # the model with a stale find schema that it can retry indefinitely.
            known_routes = discovered_adapter_routes(state)
            if not any(action == "filesystem.rename" for _, action in known_routes):
                search_tools = self._build_tools(
                    state.domain,
                    [],
                    include_gui=False,
                    include_control_tools=True,
                    strict_generic=True,
                )
                search_tools = [
                    tool
                    for tool in search_tools
                    if isinstance(tool.get("function"), dict)
                    and tool["function"].get("name") == "tools_search"
                ]
                return self._apply_common_tool_constraints(search_tools, state)
            # While observed entries remain, keep the route on the mutation
            # schema and suppress search, GUI, and terminal bypasses.
            rename_tools = self._build_tools(
                state.domain,
                ["adapter.call"],
                include_gui=False,
                include_control_tools=False,
                strict_generic=True,
            )
            return self._apply_common_tool_constraints(rename_tools, state)
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
