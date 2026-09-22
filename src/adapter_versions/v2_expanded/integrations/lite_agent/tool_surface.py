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
            adapter_call_name = tool_name("adapter.call")
            if route_pairs:
                tools = constrain_adapter_call_routes(tools, route_pairs)
            else:
                tools = [
                    tool
                    for tool in tools
                    if not isinstance(tool.get("function"), dict)
                    or tool["function"].get("name") != adapter_call_name
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
        if recovery_actions is not None:
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
        if state.requires_replan() or state.active_request_blocks():
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
        if proactive_tools:
            return self._apply_common_tool_constraints(proactive_tools, state)
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
            and (not discovery_only)
            and (not untried_required_mutations),
            include_control_tools=not discovery_only,
            strict_generic=True,
        )
        return self._apply_common_tool_constraints(tools, state)
