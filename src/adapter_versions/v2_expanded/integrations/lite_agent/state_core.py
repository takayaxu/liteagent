"""Extracted LiteAgent support module; keep application semantics generic."""

from __future__ import annotations

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .state_model import ExecutionEvent
from urllib.parse import unquote, urlparse


from . import (
    impress_semantics,
)
from .adapter_results import (
    adapter_context_hint as adapter_context_hint,
    compact_adapter_body as compact_adapter_body,
    execution_context_summary,
    has_passed_verification,
    _billing_invoice_merchant,
    _billing_invoice_total,
    _billing_statement_transactions,
    _billing_text_batch_files,
)
from .completion_policy import (
    action_is_read_only as is_read_only,
    canonical_action_request,
    action_is_save as is_save,
    effective_canonical_action,
    completion_claim_contradictions as completion_claim_contradictions,
    required_mutation_actions as collect_required_mutation_actions,
)
from .tool_catalog import (
    DIRECT_ACTION_SCHEMAS,
)


from .instruction_semantics import (
    requested_files,
    requested_ordered_image_slides,
    requested_merged_text_regions,
    requested_sheet_copy_lifecycle,
    requested_pivot_count,
    requests_appended_named_rows,
    requested_chart_count,
    requested_last_slide_duplicate_count,
    requested_slide_title_formatting,
    requested_slide_role_text_formatting,
    requested_slide_content_formatting,
    requested_content_textbox_insert,
    requested_matching_indent_without_bullet,
    instruction_required_actions,
)
from .runtime_policy import (
    argument_signature,
)
from .request_blocks import (
    is_tools_search_provenance_error,
    request_block_is_stale,
)
from .filesystem_contexts import ORGANIZATION_SKIP_ACTION
from .organization_validation import VERIFY_ACTION, classification_destinations, destination_directories


def normalize_organization_path(value: Any) -> str | None:
    """Return one lexical path identity shared by discovery, reads, and moves."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return os.path.normpath(os.path.abspath(os.path.expanduser(value.strip())))
    except (OSError, RuntimeError, ValueError):
        return value.strip().rstrip("/") or None


class RuntimeStateCoreMixin:
    _MAIL_RECIPIENT_TARGET_ROUTES = frozenset(
        {
            ("thunderbird", "compose.set_recipients"),
            # Kept as a compatibility alias for the Multi-Apps mail facade.
            ("mail", "compose_recipients"),
        }
    )
    _WORKFLOW_READ_ACTIONS = frozenset(
        {
            "workbook.read_file",
            "spreadsheet.read_file",
            "document.read_file",
            "file.read_text",
            "pdf.extract_text",
            "pdf.extract_text_batch",
            "image.extract_text_batch",
            "table.read",
            "range.read",
        }
    )
    _WORKFLOW_OPEN_ACTIONS = frozenset(
        {
            "desktop.open_path",
            "workbook.inspect",
            "document.inspect",
            "presentation.inspect",
            "spreadsheet.inspect",
        }
    )

    def requested_mail_recipient_target(self) -> bool:
        """Return whether the instruction asks to write recipients in mail.

        This is deliberately lexical and generic: it identifies the owning
        application before catalog search without extracting an address or
        selecting a route on the model's behalf.
        """
        if self.domain != "multi_apps":
            return False
        text = str(self.instruction or "").casefold()
        tokens = set(re.findall(r"[a-z0-9]+", text))
        mail_terms = {"email", "mail", "message", "messages", "draft", "compose"}
        recipient_terms = {
            "recipient",
            "recipients",
            "receiver",
            "receivers",
            "addressee",
            "addressees",
            "address",
            "addresses",
            "to",
        }
        write_terms = {
            "add",
            "append",
            "enter",
            "fill",
            "include",
            "insert",
            "place",
            "put",
            "send",
            "set",
            "update",
            "write",
        }
        has_mail = bool(tokens.intersection(mail_terms)) or bool(
            re.search(r"\be-?mail(?:s|ing)?\b", text)
        )
        return bool(
            has_mail
            and tokens.intersection(recipient_terms)
            and tokens.intersection(write_terms)
        )

    @classmethod
    def _is_mail_recipient_route(cls, domain: Any, action: Any) -> bool:
        if not isinstance(domain, str) or not isinstance(action, str):
            return False
        normalized = (domain.casefold(), action.casefold())
        return normalized in {
            (route_domain.casefold(), route_action.casefold())
            for route_domain, route_action in cls._MAIL_RECIPIENT_TARGET_ROUTES
        }

    @classmethod
    def _catalog_has_mail_recipient_route(cls, matches: Any) -> bool:
        if not isinstance(matches, list):
            return False
        for match in matches:
            if not isinstance(match, dict):
                continue
            adapter = match.get("adapter")
            downstream = match.get("downstream_action")
            if cls._is_mail_recipient_route(adapter, downstream):
                return True
            action = match.get("action")
            if isinstance(action, str) and action.casefold() in {
                "mail.compose_recipients",
                "thunderbird.compose.set_recipients",
            }:
                return True
        return False

    def _event_is_mail_recipient_route(self, event: Any) -> bool:
        domain, action, _arguments = effective_canonical_action(event, self.domain)
        if self._is_mail_recipient_route(domain, action):
            return True
        proposed = getattr(event, "proposed", {})
        if isinstance(proposed, dict):
            action_value = proposed.get("action")
            if isinstance(action_value, str) and action_value.casefold() in {
                "mail.compose_recipients",
                "thunderbird.compose.set_recipients",
            }:
                return True
        return False

    @staticmethod
    def _workflow_param_arguments(arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            return {}
        params = arguments.get("params")
        return params if isinstance(params, dict) else arguments

    @classmethod
    def _workflow_source_paths(cls, event: Any) -> set[str]:
        """Extract source identities without retaining the full read body."""
        _domain, action, arguments = effective_canonical_action(event, "")
        params = cls._workflow_param_arguments(arguments)
        paths: set[str] = set()
        for key in ("path", "input_path", "file_path", "source"):
            value = params.get(key)
            if isinstance(value, str) and value.strip() and not any(
                char in value for char in "*?[]"
            ):
                normalized = normalize_organization_path(value)
                if normalized:
                    paths.add(normalized)
        for body in cls._result_mappings(getattr(event, "result", None)):
            for key in ("path", "input_path", "file_path", "source"):
                value = body.get(key)
                if isinstance(value, str) and value.strip():
                    normalized = normalize_organization_path(value)
                    if normalized:
                        paths.add(normalized)
            files = body.get("files")
            if isinstance(files, list):
                for item in files:
                    if isinstance(item, dict) and isinstance(item.get("path"), str):
                        normalized = normalize_organization_path(item["path"])
                        if normalized:
                            paths.add(normalized)
        # A successful filesystem.find result may be nested under matches.
        for body in cls._result_mappings(getattr(event, "result", None)):
            matches = body.get("matches")
            if isinstance(matches, list):
                for item in matches:
                    value = item.get("path") if isinstance(item, dict) else item
                    if isinstance(value, str):
                        normalized = normalize_organization_path(value)
                        if normalized:
                            paths.add(normalized)
        return paths

    @classmethod
    def _workflow_read_complete(cls, event: Any) -> bool:
        """Use source-level cursors only; context projection truncation is irrelevant."""
        found_signal = False

        def visit(value: Any, source_like: bool = False) -> None:
            nonlocal found_signal
            if isinstance(value, dict):
                local_source = source_like or bool(
                    {
                        "path",
                        "input_path",
                        "source_range",
                        "returned_range",
                        "source_rows",
                        "returned_rows",
                        "display_text",
                        "sheets",
                        "files",
                    }
                    & set(value)
                )
                for key in (
                    "source_has_more",
                    "source_truncated",
                    "sheets_truncated",
                ):
                    if value.get(key) is True:
                        found_signal = False
                        raise StopIteration
                    if key in value and value.get(key) is False:
                        found_signal = True
                # ``truncated``/``has_more`` are ambiguous on an outer
                # transport wrapper. Inspect them only in a source-shaped
                # object; ``context_truncated`` is intentionally ignored.
                if local_source:
                    for key in ("has_more", "truncated"):
                        if value.get(key) is True:
                            found_signal = False
                            raise StopIteration
                        if key in value and value.get(key) is False:
                            found_signal = True
                for child in value.values():
                    visit(child, local_source)
            elif isinstance(value, list):
                for child in value:
                    visit(child, source_like)

        try:
            visit(getattr(event, "result", None))
        except StopIteration:
            return False
        return True if not found_signal else found_signal

    def workflow_progress(self) -> dict[str, Any]:
        """Return a compact, replay-free milestone ledger for model context.

        It is derived from the immutable event ledger on every call, so a soft
        restart or context compression cannot erase a completed source phase.
        """
        from . import pdf_table_selection
        from .filesystem_permission_semantics import requested_scope
        from .completion_outcomes import completion_outcome_issues

        if requested_scope(self) is not None:
            issues = completion_outcome_issues(self)
            return {"pending_phase": "outcome_verification" if issues else "outcomes_verified",
                    "outstanding_outcomes": issues}

        if pdf_table_selection.active(self):
            observed = pdf_table_selection.observations(self)
            routes = sorted(pdf_table_selection.allowed_routes(self))
            return {
                "discovered_files": sorted(pdf_table_selection.batches._observed_pdf_source_paths(self)),
                "read_sources": [{"path": item["input_path"], "reader": "os.pdf.tables.inspect", "complete": True} for item in observed.values()],
                "pending_phase": routes[0][1] if routes else "table.records.compute",
                "next_step_hint": pdf_table_selection.stage_hint(self),
            }
        discovered: set[str] = set()
        opened: set[str] = set()
        read: dict[str, dict[str, Any]] = {}
        for event in getattr(self, "events", ()):
            if not getattr(event, "executed", False):
                continue
            domain, action, _arguments = effective_canonical_action(event, self.domain)
            paths = self._workflow_source_paths(event)
            if action == "filesystem.find":
                discovered.update(paths)
            if action in self._WORKFLOW_OPEN_ACTIONS or action in self._WORKFLOW_READ_ACTIONS:
                opened.update(paths)
            if action in self._WORKFLOW_READ_ACTIONS:
                for path in paths or {"<active-source>"}:
                    read[path] = {
                        "path": path,
                        "reader": f"{domain}.{action}" if domain else action,
                        "complete": self._workflow_read_complete(event),
                    }
        if not (discovered or opened or read):
            return {}
        read_sources = list(read.values())
        complete_reads = [item for item in read_sources if item.get("complete")]
        pending_phase = "source_discovery"
        if discovered and not opened:
            pending_phase = "source_open"
        if opened and not complete_reads:
            pending_phase = "source_read"
        if complete_reads:
            pending_phase = "target_action_discovery"
        latest_read_step = max(
            (
                event.step
                for event in self.events
                if getattr(event, "executed", False)
                and effective_canonical_action(event, self.domain)[1]
                in self._WORKFLOW_READ_ACTIONS
            ),
            default=0,
        )
        if any(
            getattr(event, "executed", False)
            and getattr(event, "proposed", {}).get("kind") == "adapter"
            and event.step > latest_read_step
            and effective_canonical_action(event, self.domain)[1]
            not in self._WORKFLOW_READ_ACTIONS
            and effective_canonical_action(event, self.domain)[1]
            not in {"filesystem.find", *self._WORKFLOW_OPEN_ACTIONS}
            and (
                not self.requested_mail_recipient_target()
                or self._event_is_mail_recipient_route(event)
            )
            for event in self.events
        ):
            pending_phase = "mutation_complete"
        return {
            "discovered_files": sorted(discovered),
            "opened_sources": sorted(opened),
            "read_sources": read_sources,
            "pending_phase": pending_phase,
        }

    def source_read_handoff_pending(self) -> bool:
        """Whether a complete source read should hand the model to catalog search."""
        if self.domain != "multi_apps":
            return False
        progress = self.workflow_progress()
        if progress.get("pending_phase") != "target_action_discovery":
            return False
        # A source read is a handoff only while no later non-read route has
        # succeeded. This keeps read-only tasks eligible for normal completion.
        latest_read = next(
            (
                event
                for event in reversed(self.events)
                if getattr(event, "executed", False)
                and effective_canonical_action(event, self.domain)[1]
                in self._WORKFLOW_READ_ACTIONS
            ),
            None,
        )
        if latest_read is None or not self._workflow_read_complete(latest_read):
            return False
        latest_read_step = latest_read.step
        latest_catalog = next(
            (
                event
                for event in reversed(self.events)
                if getattr(event, "executed", False)
                and getattr(event, "proposed", {}).get("kind") == "catalog"
                and event.step > latest_read_step
            ),
            None,
        )
        if latest_catalog is not None:
            matches = (
                latest_catalog.result.get("matches", [])
                if isinstance(latest_catalog.result, dict)
                else []
            )
            if self.requested_mail_recipient_target():
                # A Calc or generic writer result is not a valid lease for a
                # mail recipient task. Keep the search-only surface until the
                # owning mail route is explicitly returned by the catalog.
                return not self._catalog_has_mail_recipient_route(matches)
            # A search that only rediscovered the reader has not advanced the
            # phase; keep search exposed until a different public operation is
            # found. A mutation route, however, leases the next phase.
            if not any(
                isinstance(match, dict)
                and match.get("action") == "adapter.call"
                and match.get("downstream_action") not in self._WORKFLOW_READ_ACTIONS
                for match in matches
            ):
                return True
            return False
        if any(
            getattr(event, "executed", False)
            and getattr(event, "proposed", {}).get("kind") == "adapter"
            and event.step > latest_read_step
            and effective_canonical_action(event, self.domain)[1]
            not in self._WORKFLOW_READ_ACTIONS
            and effective_canonical_action(event, self.domain)[1]
            not in {"filesystem.find", "workbook.inspect"}
            and (
                not self.requested_mail_recipient_target()
                or self._event_is_mail_recipient_route(event)
            )
            for event in self.events
        ):
            return False
        # Keep this generic: these are operation words, not a task or target
        # application name. The catalog still decides the concrete route.
        if self.requested_mail_recipient_target():
            return True
        return bool(
            re.search(
                r"(?i)\b(add|append|apply|change|compose|create|delete|edit|enter|fill|insert|move|send|set|update|write|receiver|recipient)\b",
                str(self.instruction),
            )
        )

    def source_read_target_search_complete(self) -> bool:
        """Return whether catalog search found a post-read non-reader route."""
        latest_read_step = max(
            (
                event.step
                for event in self.events
                if getattr(event, "executed", False)
                and effective_canonical_action(event, self.domain)[1]
                in self._WORKFLOW_READ_ACTIONS
            ),
            default=0,
        )
        if not latest_read_step:
            return False
        for event in reversed(self.events):
            if not getattr(event, "executed", False) or event.step <= latest_read_step:
                continue
            proposed = getattr(event, "proposed", {})
            if not isinstance(proposed, dict) or proposed.get("kind") != "catalog":
                continue
            matches = event.result.get("matches", []) if isinstance(event.result, dict) else []
            if self.requested_mail_recipient_target():
                return self._catalog_has_mail_recipient_route(matches)
            return any(
                isinstance(match, dict)
                and match.get("action") == "adapter.call"
                and match.get("downstream_action") not in self._WORKFLOW_READ_ACTIONS
                for match in matches
            )
        return False

    def begin_same_vm_soft_restart(
        self,
        reason: str,
        *,
        max_retries: int = 1,
        trigger_step: int | None = None,
        context_limit: int = 8,
    ) -> Any:
        """Delegate the generic in-place recovery transition lazily."""
        from .episode_control import begin_same_vm_soft_restart

        return begin_same_vm_soft_restart(
            self,
            reason,
            max_retries=max_retries,
            trigger_step=trigger_step,
            context_limit=context_limit,
        )

    def mark_tool_result_for_audit(self, event: Any) -> dict[str, Any]:
        """Register an event as requiring the next model audit."""
        from .episode_control import mark_tool_result_for_audit

        return mark_tool_result_for_audit(self, event)

    def record_model_audit(self, proposal: Any) -> dict[str, Any] | None:
        """Record the next complete model turn as the pending event audit."""
        from .episode_control import record_model_audit

        return record_model_audit(self, proposal)

    def has_pending_model_audit(self) -> bool:
        return isinstance(getattr(self, "pending_model_audit", None), dict)

    def successful_adapter_events(self) -> list[ExecutionEvent]:
        return [
            event
            for event in self.events
            if event.executed and event.proposed.get("kind") == "adapter"
        ]

    def context_summary(
        self, limit: int = 12, *, strict_generic: bool = False
    ) -> list[dict[str, Any]]:
        summary = execution_context_summary(
            self.events,
            self.domain,
            limit=limit,
            strict_generic=strict_generic,
        )
        observation = self.filesystem_observation_state()
        progress = self.workflow_progress()
        if progress:
            # Completion readiness outranks the generic source workflow label.
            from .completion import CompletionMixin
            from .completion_review import review_ready
            if self.done:
                progress = {**progress, "pending_phase": "complete"}
            elif review_ready(self, CompletionMixin._generic_completion_gate(self)):
                progress = {**progress, "pending_phase": "completion_review"}
            # This marker is intentionally before ordinary event history. It
            # is a phase ledger, not a replayable result, and must survive fit.
            summary = [{"workflow_progress": progress}, *summary]
        if observation is not None:
            # Keep the phase transition ahead of the bounded event transcript;
            # this is the model-facing state machine edge, not new evidence.
            summary = [{"filesystem_observation": observation}, *summary]
        # A soft restart replaces only the transient reasoning context.  Keep
        # the compact recovery handoff visible for its bounded follow-up
        # window, while leaving the immutable event ledger untouched underneath.
        recovery = getattr(self, "recovery_context", None)
        pending_audit = getattr(self, "pending_model_audit", None)
        pending_terminal = getattr(self, "pending_terminal", None)
        if (
            not isinstance(recovery, dict)
            and not isinstance(pending_audit, dict)
            and not isinstance(pending_terminal, dict)
        ) or limit <= 0:
            # execution_context_summary already keeps the latest limit events.
            # Prefix markers must not evict the newest correction/readback.
            return summary if limit > 0 else []
        markers: list[dict[str, Any]] = []
        if isinstance(recovery, dict):
            # Keep the successful mutation ledger in its own bounded marker.
            # The pending-audit and recovery markers can consume the whole
            # compact limit; promoting this projection preserves the latest
            # model-selected targets without changing the authoritative events.
            recovery_view = dict(recovery)
            mutation_ledger = recovery_view.pop("successful_mutation_ledger", None)
            if isinstance(mutation_ledger, list) and mutation_ledger:
                markers.append({"recovery_mutation_ledger": mutation_ledger})
            markers.append({"recovery_context": recovery_view})
        if isinstance(pending_audit, dict):
            markers.append(
                {
                    "model_audit_required": {
                        key: pending_audit[key]
                        for key in ("event_step", "tool_class", "status")
                        if key in pending_audit
                    }
                }
            )
        if isinstance(pending_terminal, dict):
            markers.append(
                {
                    "terminal_result_pending_audit": {
                        key: pending_terminal[key]
                        for key in ("event_step", "tool", "status")
                        if key in pending_terminal
                    }
                }
            )
        # The limit already bounds recent events. Trimming this chronological
        # summary again would remove the newest result named by the audit marker.
        return [*markers[:limit], *summary]

    def filesystem_organization_reference_observations(self) -> list[dict[str, Any]]:
        """Retain observed comparison evidence across single-object transitions."""
        if not re.search(
            r"(?i)\b(?:cross[ -]?check|compar(?:e|ing|ison)|reconcil(?:e|ing|iation)|match(?:ing)?)\b",
            self.instruction,
        ):
            return []
        marker = self.filesystem_observation_state()
        current = self.filesystem_organization_current_entry()
        if not isinstance(marker, dict) or current is None:
            return []
        references: list[dict[str, Any]] = []
        for entry in marker.get("observed_entries", []):
            if not isinstance(entry, dict) or entry.get("path") == current.get("path"):
                continue
            observation = self.filesystem_organization_evidence(entry)
            # Launcher screenshots are transient, not durable document reads.
            if observation and observation.get("action") != "desktop.open_path":
                result = observation.get("result")
                if isinstance(result, dict):
                    # Historical workflow markers are not reference content:
                    # they must not compete with the current object marker.
                    observation = {
                        **observation,
                        "result": {key: value for key, value in result.items() if key != "organization_progress"},
                    }
                references.append({"source": entry, "observation": observation})
        return references

    def filesystem_organization_model_context(
        self, limit: int = 4
    ) -> list[dict[str, Any]]:
        """Project organization state without replayable historical paths."""
        observation = self.filesystem_observation_state()
        if not isinstance(observation, dict) or observation.get("complete") is not True:
            return self.context_summary(limit=limit, strict_generic=True)

        progress = self.filesystem_organization_progress(model_visible=True)
        projected: list[dict[str, Any]] = [
            {
                "filesystem_observation": {
                    "complete": True,
                    "current_object": progress.get("current_object"),
                    "current_object_status": progress.get("current_object_status"),
                }
            },
            {"organization_progress": progress},
        ]
        projected.append({"destination_directories": self.filesystem_organization_destinations()})
        evidence = self.filesystem_organization_evidence()
        if evidence:
            projected.append({"current_object_observation": evidence})
        references = self.filesystem_organization_reference_observations()
        if references:
            projected.append({"comparison_reference_observations": references})
        check = self.filesystem_organization_check()
        if check:
            projected.append({"classification_check": check})
        latest = self.events[-1] if self.events else None
        if latest is None:
            return projected
        _domain, action, _arguments = effective_canonical_action(latest, self.domain)
        reader_actions = {
            "pdf.extract_text_batch",
            "file.read_text",
            "document.read_file",
            "workbook.read_file",
            "spreadsheet.read_file",
            "image.extract_text_batch",
            "desktop.open_path",
        }
        event_projection = execution_context_summary(
            [latest], self.domain, limit=1, strict_generic=True
        )
        if not event_projection:
            return projected
        event_view = event_projection[-1]
        # Hide replayable arguments. Keep only the latest reader result because
        # it is the evidence needed to classify the active object.
        event_view["arguments"] = {}
        if (action in reader_actions or action == VERIFY_ACTION) and latest.executed:
            projected.append(event_view)
        elif not latest.executed:
            projected.append(
                {
                    "step": event_view.get("step"),
                    "executed": False,
                    "error": event_view.get("error"),
                }
            )
        return projected

    def filesystem_observation_state(self) -> dict[str, Any] | None:
        """Return the completed discovery phase for a file-organization task.

        The marker is derived only from a successful, bounded ``kind=any``
        result.  It deliberately carries exact observed paths so the next
        phase can classify and rename those objects without searching again.
        """
        if self.domain != "multi_apps" or not self.filesystem_move_requested():
            return None
        for event in self.successful_adapter_events():
            domain, action, arguments = effective_canonical_action(event, self.domain)
            if (domain, action) != ("os", "filesystem.find"):
                continue
            params = arguments.get("params", arguments) if isinstance(arguments, dict) else {}
            if not isinstance(params, dict) or params.get("kind") != "any":
                continue
            patterns = params.get("name_patterns")
            # A literal category-folder probe (for example, "problematic") is
            # not a new source inventory. Keep the original wildcard scan as
            # the authoritative observed-entry set for the mutation phase.
            if (
                isinstance(patterns, list)
                and patterns
                and all(
                    isinstance(pattern, str)
                    and not any(char in pattern for char in "*?")
                    for pattern in patterns
                )
            ):
                continue
            marker: dict[str, Any] | None = None
            for body in self._result_mappings(event.result):
                nested = body.get("downstream_context")
                candidate = nested if isinstance(nested, dict) else body
                inventory = getattr(self, "filesystem_organization_inventory", None)
                if not isinstance(inventory, list):
                    inventory = candidate.get("matches")
                if not isinstance(inventory, list):
                    continue
                if not isinstance(getattr(self, "filesystem_organization_inventory", None), list) and candidate.get("truncated") is True:
                    continue
                matches = [
                    {
                        key: item.get(key)
                        for key in ("path", "name", "kind")
                        if key in item
                    }
                    for item in inventory
                    if isinstance(item, dict) and isinstance(item.get("path"), str)
                ]
                destinations = destination_directories(self.instruction, matches)
                for prior in self.events:
                    result = getattr(prior, "result", None)
                    _domain, prior_action, _arguments = effective_canonical_action(prior, self.domain)
                    if prior_action == VERIFY_ACTION and prior.executed and isinstance(result, dict) and result.get("instruction") == self.instruction and result.get("passed") is True and result.get("disposition") == "move":
                        destination = result.get("destination_directory")
                        if isinstance(destination, str) and destination not in destinations:
                            destinations.append(destination)
                matches = [item for item in matches if not (
                    item.get("kind") == "directory" and item.get("path") in destinations
                )]
                roots = params.get("roots")
                root_list = [str(root) for root in roots] if isinstance(roots, list) else []
                marker = {
                    "complete": True,
                    "observed_roots": root_list,
                    "observed_entries": matches,
                    "destination_directories": destinations,
                    "next_required_phase": "classify_and_move",
                    "next_required_actions": [
                        "process exactly one current object at a time",
                        "read content when name and extension are not conclusive",
                        "filesystem.rename the classified object to its category folder",
                    ],
                    "classification_policy": [
                        "Use the classification criteria and exact destination folder names from the user instruction.",
                        "Choose each object's destination from its observed content; preserve its exact basename.",
                        "If the instruction requires leaving an object in place, classify it with organization__skip_current and continue to the next object.",
                    ],
                    "content_evidence_required": (
                        "Every ambiguous object requires a successful content observation before it can be moved; PDF is not a special workflow."
                    ),
                    "forbidden_next_action": "repeat filesystem.find for an observed root",
                }
                moved: set[str] = set()
                for prior in self.successful_adapter_events():
                    prior_domain, prior_action, prior_arguments = effective_canonical_action(prior, self.domain)
                    if (prior_domain, prior_action) == ("os", "filesystem.rename"):
                        source = prior_arguments.get("source") if isinstance(prior_arguments, dict) else None
                        normalized = normalize_organization_path(source)
                        if normalized:
                            moved.add(normalized)
                pending = {
                    normalize_organization_path(item.get("path"))
                    for item in matches
                    if isinstance(item, dict)
                    and normalize_organization_path(item.get("path"))
                    and normalize_organization_path(item.get("path")) not in moved
                }
                current = next(
                    (item for item in matches if normalize_organization_path(item.get("path")) in pending),
                    None,
                )
                if current is not None:
                    marker["current_object"] = current
                    marker["current_object_requires_content"] = not self._organization_object_is_certain(current)
                break
            if marker is not None:
                return marker
        return None

    def filesystem_organization_destinations(self) -> list[str]:
        marker = self.filesystem_observation_state()
        return marker.get("destination_directories", []) if isinstance(marker, dict) else []

    def filesystem_organization_candidates(self, entry: dict[str, Any]) -> list[str]:
        return classification_destinations(self, entry)[0]

    def filesystem_organization_evidence(self, entry: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Keep the current observation through check/retry turns; opening is not reading."""
        current = entry or self.filesystem_organization_current_entry()
        if not current:
            return None
        for event in reversed(self.successful_adapter_events()):
            domain, action, arguments = effective_canonical_action(event, self.domain)
            if action not in {
                "pdf.extract_text_batch", "image.extract_text_batch", "workbook.read_file",
                "document.read_file", "file.read_text", "desktop.open_path", "filesystem.find",
            }:
                continue
            params = arguments.get("params", arguments)
            if current.get("kind") == "directory":
                if action != "filesystem.find" or params.get("roots") != [current["path"]] or params.get("recursive") is not True:
                    continue
                hint = event.result.get("context_hint", event.result) if isinstance(event.result, dict) else None
                return {"step": event.step, "adapter": domain, "action": action, "result": hint}
            if action == "filesystem.find":
                continue
            requested = next((params.get(key) for key in ("path", "input_path", "file_path", "input_pattern") if params.get(key)), None)
            if normalize_organization_path(requested) != normalize_organization_path(current.get("path")):
                continue
            hint = event.result.get("context_hint", event.result) if isinstance(event.result, dict) else None
            return {"step": event.step, "adapter": domain, "action": action, "result": hint}
        return None

    def filesystem_organization_check(self, entry: dict[str, Any] | None = None) -> dict[str, Any] | None:
        current = entry or self.filesystem_organization_current_entry()
        if not current:
            return None
        evidence = self.filesystem_organization_evidence(current)
        for event in reversed(self.events):
            _domain, action, _args = effective_canonical_action(event, self.domain)
            check = event.result
            if action != VERIFY_ACTION or not event.executed or not isinstance(check, dict):
                continue
            if check.get("path") != current.get("path"):
                continue
            if check.get("instruction") != self.instruction or check.get("observation_step") != (evidence.get("step") if evidence else None):
                return None
            return check if check.get("passed") is True else None
        return None

    def filesystem_organization_unverified_move(self, entry: dict[str, Any]) -> bool:
        """An executed but unverified move is not safe to blindly repeat."""
        for event in reversed(self.events):
            domain, action, arguments = effective_canonical_action(event, self.domain)
            if (domain, action) == ("os", "filesystem.rename") and arguments.get("source") == entry.get("path") and event.executed:
                return not has_passed_verification(event.result)
        return False

    def filesystem_organization_requested(self) -> bool:
        """Return true only for instructions that organize filesystem objects."""
        if self.domain != "multi_apps":
            return False
        instruction = str(self.instruction)
        intent = re.search(
            r"(?i)\b(?:organize|organization|categorize|classify|place|put|move|relocate|rename)\b",
            instruction,
        )
        filesystem_object = re.search(
            r"(?i)\b(?:files?|folders?|directories|directory|file\s+system|file-manager|category\s+folders?)\b",
            instruction,
        )
        return bool(intent and filesystem_object)

    def filesystem_move_requested(self) -> bool:
        """Return true for directory/file moves, excluding output-table wording."""
        if not self.filesystem_organization_requested():
            return False
        instruction = str(self.instruction)
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

    def filesystem_organization_pending_entries(self) -> list[str]:
        """Return observed source paths that have not been resolved yet."""
        marker = self.filesystem_observation_state()
        if not isinstance(marker, dict) or marker.get("complete") is not True:
            return []
        observed = {
            normalized
            for item in marker.get("observed_entries", [])
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and item.get("path")
            and (normalized := normalize_organization_path(item.get("path")))
        }
        ledger = self.filesystem_organization_progress().get("objects", {})
        return sorted(
            path
            for path in observed
            if not (
                isinstance(ledger.get(path), dict)
                and ledger[path].get("classified") is True
                and (
                    ledger[path].get("moved") is True
                    or ledger[path].get("skipped") is True
                )
            )
        )

    def filesystem_organization_progress(
        self, *, model_visible: bool = False
    ) -> dict[str, Any]:
        """Reconcile organization state and optionally return its compact model view.

        The full ledger remains runner-owned for exact pending/current checks.  The
        model only needs the reusable state machine marker for the active object;
        exposing every historical object snapshot makes stale actions attractive
        after a large reader response is projected into context.
        """
        marker = self.filesystem_observation_state()
        if not isinstance(marker, dict) or marker.get("complete") is not True:
            if model_visible:
                return {
                    "current_object": None,
                    "current_object_status": {
                        "classified": False,
                        "moved": False,
                    },
                }
            return {"objects": {}, "all_objects_completed": False}
        objects: dict[str, dict[str, Any]] = {}
        source_entries: dict[str, dict[str, Any]] = {}
        for item in marker.get("observed_entries", []):
            if not isinstance(item, dict):
                continue
            path = normalize_organization_path(item.get("path"))
            if not path:
                continue
            source_entries[path] = {**item, "path": path}
            objects[path] = {
                "path": path,
                "classified": False,
                "moved": False,
                "read": False,
                "category": None,
            }
        for path in self.filesystem_organization_read_paths():
            if path in objects:
                objects[path]["read"] = True
        for event in self.successful_adapter_events():
            domain, action, arguments = effective_canonical_action(event, self.domain)
            if (domain, action) != ("os", "filesystem.rename"):
                continue
            source = arguments.get("source") if isinstance(arguments, dict) else None
            path = normalize_organization_path(source)
            if path not in objects:
                continue
            destination = arguments.get("destination")
            check = self.filesystem_organization_check(source_entries[path])
            if not check or check.get("disposition") != "move" or (
                not isinstance(destination, str)
                or normalize_organization_path(os.path.dirname(destination)) != check.get("destination_directory")
                or not has_passed_verification(event.result)
            ):
                continue
            category = None
            if isinstance(destination, str):
                parts = destination.rstrip("/").split("/")
                if len(parts) >= 2:
                    category = parts[-2]
            objects[path].update(
                {"classified": True, "moved": True, "category": category}
            )
        for event in self.events:
            if not getattr(event, "executed", False):
                continue
            _domain, action, arguments = effective_canonical_action(event, self.domain)
            if action != ORGANIZATION_SKIP_ACTION or not isinstance(arguments, dict):
                continue
            path = normalize_organization_path(arguments.get("path"))
            if path not in objects:
                continue
            check = self.filesystem_organization_check(source_entries[path])
            if not check or check.get("disposition") != "retain" or check.get("destination_directory") != os.path.dirname(path):
                continue
            objects[path].update(
                {
                    "classified": True,
                    "moved": False,
                    "skipped": True,
                    "category": None,
                    "reason": arguments.get("reason"),
                }
            )
        self.filesystem_organization_ledger = objects
        pending = [
            path
            for path, status in objects.items()
            if not (
                status["classified"]
                and (status["moved"] or status.get("skipped") is True)
            )
        ]
        current = None
        active_path = normalize_organization_path(
            getattr(self, "filesystem_organization_active_path", None)
        )
        candidate_paths = set(pending)
        if active_path in candidate_paths:
            current = next(
                (
                    item
                    for item in marker.get("observed_entries", [])
                    if normalize_organization_path(item.get("path")) == active_path
                ),
                None,
            )
        if current is None:
            current = next(
                (
                    item
                    for item in marker.get("observed_entries", [])
                    if normalize_organization_path(item.get("path")) in candidate_paths
                ),
                None,
            )
        progress = {
            "objects": objects,
            "completed_objects": [
                path
                for path, status in objects.items()
                if status["classified"]
                and (status["moved"] or status.get("skipped") is True)
            ],
            "pending_objects": pending,
            "current_object": current.get("path") if current else None,
            "current_object_status": (
                objects.get(current.get("path"), {}) if current else None
            ),
            "all_objects_completed": bool(objects) and not pending,
        }
        if not model_visible:
            return progress
        current_status = progress["current_object_status"]
        return {
            "current_object": progress["current_object"],
            "current_object_status": {
                "classified": bool(
                    isinstance(current_status, dict)
                    and current_status.get("classified") is True
                ),
                "moved": bool(
                    isinstance(current_status, dict)
                    and current_status.get("moved") is True
                ),
            },
        }

    def filesystem_organization_current_entry(self) -> dict[str, Any] | None:
        """Return the first unresolved object in deterministic inventory order."""
        marker = self.filesystem_observation_state()
        if not isinstance(marker, dict) or marker.get("complete") is not True:
            return None
        progress = self.filesystem_organization_progress()
        pending = set(progress.get("pending_objects", []))
        active_path = normalize_organization_path(
            getattr(self, "filesystem_organization_active_path", None)
        )
        if active_path in pending:
            for item in marker.get("observed_entries", []):
                if normalize_organization_path(item.get("path")) == active_path:
                    return {**item, "path": active_path}
        for item in marker.get("observed_entries", []):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            path = normalize_organization_path(item["path"])
            if path in pending:
                return {**item, "path": path}
        return None

    @staticmethod
    def _organization_object_is_certain(entry: dict[str, Any]) -> bool:
        """Only unambiguous, strongly typed source files may skip inspection."""
        if entry.get("kind") != "file":
            return False
        name = str(entry.get("name") or entry.get("path") or "").casefold()
        suffix = name.rsplit(".", 1)[-1] if "." in name else ""
        # Source-code extensions identify their content type.  Documents,
        # archives, PDFs, and unknown extensions remain content-sensitive.
        return suffix in {
            "py", "js", "jsx", "ts", "tsx", "java", "c", "h", "cpp", "cc",
            "cxx", "go", "rs", "rb", "php", "swift", "kt", "kts", "scala",
            "sh", "bash", "zsh", "fish", "sql", "html", "css",
        }

    def filesystem_organization_read_paths(self) -> set[str]:
        """Return sources with successful per-object content evidence."""
        paths: set[str] = set()
        reader_actions = {
            "pdf.extract_text_batch", "file.read_text", "document.read_file",
            "workbook.read_file", "spreadsheet.read_file",
            "image.extract_text_batch", "filesystem.find",
        }
        for event in self.successful_adapter_events():
            domain, action, arguments = effective_canonical_action(event, self.domain)
            if action not in reader_actions:
                continue
            params = arguments.get("params", arguments) if isinstance(arguments, dict) else {}
            if action == "filesystem.find":
                if params.get("recursive") is True:
                    paths.update(path for root in params.get("roots", []) if (path := normalize_organization_path(root)))
                continue
            for key in ("input_path", "path", "file_path"):
                value = params.get(key) if isinstance(params, dict) else None
                if isinstance(value, str) and not any(char in value for char in "*?[]"):
                    normalized = normalize_organization_path(value)
                    if normalized:
                        paths.add(normalized)
            for body in self._result_mappings(getattr(event, "result", None)):
                for key in ("path", "input_path"):
                    value = body.get(key)
                    if isinstance(value, str):
                        normalized = normalize_organization_path(value)
                        if normalized:
                            paths.add(normalized)
                files = body.get("files")
                if isinstance(files, list):
                    for item in files:
                        if isinstance(item, dict) and isinstance(item.get("path"), str):
                            normalized = normalize_organization_path(item["path"])
                            if normalized:
                                paths.add(normalized)
        return paths

    def filesystem_organization_requires_content(self, entry: dict[str, Any] | None = None) -> bool:
        current = entry or self.filesystem_organization_current_entry()
        return bool(current and not self._organization_object_is_certain(current))

    def filesystem_organization_current_is_bank_statement(
        self, entry: dict[str, Any] | None = None
    ) -> bool:
        """Identify a read bank statement that should be retained in place.

        Billing reconciliation treats the statement as evidence, not as an
        invoice to move.  Once its exact PDF has been read successfully, keep
        the organization surface on the explicit retain transition so a model
        cannot turn a no-op rename into a mutation attempt.
        """
        instruction = str(self.instruction).casefold()
        if "invoice" not in instruction or not any(
            token in instruction
            for token in ("statement", "transaction", "discrepanc", "match")
        ):
            return False
        current = entry or self.filesystem_organization_current_entry()
        if not isinstance(current, dict):
            return False
        current_path = normalize_organization_path(current.get("path"))
        if not current_path or current_path not in self.filesystem_organization_read_paths():
            return False
        for event in self.successful_adapter_events():
            domain, action, _arguments = effective_canonical_action(event, self.domain)
            if (domain, action) != ("os", "pdf.extract_text_batch"):
                continue
            for item in _billing_text_batch_files(getattr(event, "result", None)):
                path = normalize_organization_path(item.get("path"))
                text = item.get("text")
                if path != current_path or not isinstance(text, str):
                    continue
                corpus = f"{path} {text}".casefold()
                if (
                    "bank-statement" in corpus
                    or "bank statement" in corpus
                    or "statement" in corpus
                    or "transactions" in corpus
                ):
                    return True
        return False

    def filesystem_organization_reader_route(self, entry: dict[str, Any] | None = None) -> tuple[str, str]:
        """Choose the bounded reader for one ambiguous current object."""
        current = entry or self.filesystem_organization_current_entry() or {}
        if current.get("kind") == "directory":
            return ("os", "filesystem.find")
        name = str(current.get("name") or current.get("path") or "").casefold()
        suffix = name.rsplit(".", 1)[-1] if "." in name else ""
        if suffix == "pdf":
            return ("os", "pdf.extract_text_batch")
        if suffix in {"doc", "docx", "odt", "rtf"}:
            return ("libreoffice_writer", "document.read_file")
        if suffix in {"csv", "xlsx", "ods"}:
            return ("libreoffice_calc", "workbook.read_file")
        if suffix in {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp"}:
            return ("os", "image.extract_text_batch")
        if suffix in {"txt", "md", "json", "xml", "yaml", "yml", "log"}:
            return ("vs_code", "file.read_text")
        # Binary/opaque formats are inspected through the desktop opener so
        # their content is observed by the owning application rather than
        # decoded as UTF-8 text by VS Code.
        return ("os", "desktop.open_path")

    def filesystem_organization_observed_pdf_paths(self) -> set[str]:
        """Return normalized PDFs from the authoritative filesystem inventory."""
        marker = self.filesystem_observation_state()
        if not isinstance(marker, dict) or marker.get("complete") is not True:
            return set()
        paths: set[str] = set()
        for item in marker.get("observed_entries", []):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            raw = item["path"]
            normalized = normalize_organization_path(raw)
            if normalized and normalized.casefold().endswith(".pdf"):
                paths.add(normalized)
        return paths

    def filesystem_organization_read_pdf_paths(self) -> set[str]:
        """Return normalized PDF paths actually returned by successful readers."""
        paths: set[str] = set()
        for event in self.successful_adapter_events():
            domain, action, _arguments = effective_canonical_action(event, self.domain)
            if (domain, action) != ("os", "pdf.extract_text_batch"):
                continue
            for body in self._result_mappings(getattr(event, "result", None)):
                files = body.get("files")
                if not isinstance(files, list):
                    continue
                for item in files:
                    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                        continue
                    if item.get("status") not in (None, "ok"):
                        continue
                    normalized = normalize_organization_path(item["path"])
                    if normalized and normalized.casefold().endswith(".pdf"):
                        paths.add(normalized)
        return paths

    def filesystem_organization_complete(self) -> bool:
        marker = self.filesystem_observation_state()
        if not self.filesystem_move_requested() and self._billing_reconciliation_complete():
            return True
        return bool(
            isinstance(marker, dict)
            and marker.get("complete") is True
            and not self.filesystem_organization_pending_entries()
        )

    def _billing_reconciliation_complete(self) -> bool:
        """Finish billing moves only after every unmatched invoice was moved."""
        instruction = str(self.instruction).casefold()
        if "invoice" not in instruction or not any(
            token in instruction for token in ("statement", "transaction", "discrepanc", "match")
        ):
            return False
        observations: list[dict[str, Any]] = []
        moved: set[str] = set()
        for event in self.events:
            if not getattr(event, "executed", False):
                continue
            domain, action, arguments = effective_canonical_action(event, self.domain)
            if (domain, action) == ("os", "filesystem.rename"):
                source = arguments.get("source") if isinstance(arguments, dict) else None
                if isinstance(source, str):
                    moved.add(source.rstrip("/"))
                continue
            if (domain, action) != ("os", "pdf.extract_text_batch"):
                continue
            observations.extend(_billing_text_batch_files(getattr(event, "result", None)))
        statements: list[tuple[set[str], list[tuple[set[str], set[float]]]]] = []
        invoices: dict[str, tuple[float, set[str]]] = {}
        for item in observations:
            path = item.get("path")
            text = item.get("text")
            if not isinstance(path, str) or not isinstance(text, str):
                continue
            corpus = f"{path} {text}".casefold()
            if "statement" in corpus or "transactions" in corpus or "bank-statement" in corpus:
                statements.append((set(), _billing_statement_transactions(text)))
            elif "invoice" in corpus or "balance due" in corpus or "invoice total" in corpus:
                total = _billing_invoice_total(text)
                if total is not None:
                    invoices[path] = (total, _billing_invoice_merchant(text))
        if not statements or not invoices:
            return False
        rows = [row for _, rows in statements for row in rows]
        for path, (total, merchant) in invoices.items():
            matched = any(
                total in amounts and bool(merchant) and merchant <= row_tokens
                for row_tokens, amounts in rows
            )
            if not matched and path.rstrip("/") not in moved:
                return False
        return True

    def requires_replan(self) -> bool:
        if not self.events:
            return False
        error = self.events[-1].error
        return isinstance(error, dict) and error.get("type") == "RepeatedActionBlocked"

    def active_request_blocks(self) -> dict[str, dict[str, Any]]:
        next_step = len(self.events) + 1
        blocks: dict[str, dict[str, Any]] = {}
        for event in self.events:
            error = event.error
            if (
                not isinstance(error, dict)
                or error.get("type") != "RepeatedActionBlocked"
            ):
                continue
            action = error.get("blocked_action")
            arguments_signature = error.get("argument_signature")
            blocked_until_step = error.get("blocked_until_step")
            if not isinstance(action, str) or not isinstance(arguments_signature, str):
                continue
            block_scope = error.get("block_scope", "window")
            if block_scope == "episode" or (
                isinstance(blocked_until_step, int) and next_step <= blocked_until_step
            ):
                if request_block_is_stale(self.events, blocked_at_step=event.step):
                    continue
                key = f"{action}:{arguments_signature}:{error.get('error_signature')!r}"
                blocks[key] = {
                    "action": action,
                    "argument_signature": arguments_signature,
                    "blocked_at_step": event.step,
                    "blocked_until_step": blocked_until_step,
                    "block_scope": block_scope,
                    "error_signature": error.get("error_signature"),
                    "previous_error": error.get("previous_error"),
                    "fallback_reason": error.get("fallback_reason"),
                }
                arguments = event.proposed.get("arguments")
                canonical_domain, canonical_action, canonical_arguments = (
                    canonical_action_request(
                        self.domain,
                        action,
                        arguments,
                    )
                )
                blocks[key]["canonical_domain"] = canonical_domain
                blocks[key]["canonical_action"] = canonical_action
                blocks[key]["canonical_argument_signature"] = argument_signature(
                    canonical_arguments
                )
                if action == "adapter.call" and isinstance(arguments, dict):
                    downstream_adapter = arguments.get("adapter")
                    downstream_action = arguments.get("action")
                    if isinstance(downstream_adapter, str) and isinstance(
                        downstream_action, str
                    ):
                        blocks[key]["downstream_route"] = {
                            "adapter": downstream_adapter,
                            "action": downstream_action,
                        }
        return blocks

    def blocked_routes(self) -> set[tuple[str, str]]:
        routes: set[tuple[str, str]] = set()
        for block in self.active_request_blocks().values():
            # A missing catalog result is a protocol-ordering error, not a
            # failed downstream route. Keep the route searchable so the model
            # can obtain the required provenance without inventing a path.
            if is_tools_search_provenance_error(block.get("previous_error")):
                continue
            route = block.get("downstream_route")
            if (
                isinstance(route, dict)
                and isinstance(route.get("adapter"), str)
                and isinstance(route.get("action"), str)
            ):
                schema = DIRECT_ACTION_SCHEMAS.get(route["adapter"], {}).get(route["action"])
                # Parameterized routes remain discoverable with different
                # arguments. Only a parameterless route is one exact request.
                if schema is not None and not schema.get("properties"):
                    routes.add((route["adapter"], route["action"]))
        return routes

    def active_request_block(
        self, action: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        canonical_domain, canonical_action, canonical_arguments = (
            canonical_action_request(self.domain, action, arguments)
        )
        signature = argument_signature(canonical_arguments)
        return next(
            (
                block
                for block in self.active_request_blocks().values()
                if block.get("canonical_domain", self.domain) == canonical_domain
                and block.get("canonical_action", block["action"]) == canonical_action
                and block.get(
                    "canonical_argument_signature", block["argument_signature"]
                )
                == signature
            ),
            None,
        )

    def active_action_blocks(self) -> dict[str, dict[str, Any]]:
        blocks: dict[str, dict[str, Any]] = {}
        for block in self.active_request_blocks().values():
            blocks.setdefault(block["action"], block)
        return blocks

    def blocked_actions(self) -> set[str]:
        blocked: set[str] = set()
        for block in self.active_request_blocks().values():
            action = block["action"]
            schema = DIRECT_ACTION_SCHEMAS.get(self.domain, {}).get(action)
            if schema is not None and not schema.get("properties"):
                blocked.add(action)
        return blocked

    def recovery_search_pending_choice(self) -> bool:
        if not self.events:
            return False
        event = self.events[-1]
        if not event.executed or event.proposed.get("kind") != "catalog":
            return False
        result = event.result
        return bool(
            isinstance(result, dict)
            and isinstance(result.get("recovery"), dict)
            and result["recovery"].get("trigger") == "repeated_action"
        )

    def recommended_mutations_satisfied(self) -> bool:
        required = self.required_mutation_actions()
        if not required:
            return False
        if self.annual_percentage_change_request() is not None:
            return self.annual_percentage_change_mutations_satisfied()
        if self.monthly_column_totals_request() is not None:
            return self.monthly_column_totals_mutations_satisfied()
        if requested_sheet_copy_lifecycle(self.instruction) is not None:
            return self.sheet_copy_lifecycle_mutations_satisfied()
        if requested_slide_title_formatting(self.instruction) is not None:
            return self.slide_title_format_mutations_satisfied()
        if requested_slide_content_formatting(self.instruction) is not None:
            return self.slide_content_format_mutations_satisfied()
        if requested_slide_role_text_formatting(self.instruction) is not None:
            return self.slide_role_text_format_mutations_satisfied()
        for action in required:
            if (
                action
                in {
                    "slide.delete",
                    "shape.delete",
                    "slide.create",
                    "shape.insert_image",
                }
                and requested_ordered_image_slides(self.instruction) is not None
            ):
                if not self.ordered_image_slide_mutations_satisfied():
                    return False
            elif action == "slide.duplicate":
                count = requested_last_slide_duplicate_count(self.instruction)
                if (
                    count is not None
                    and len(self.successful_action_events(action)) < count
                ):
                    return False
            elif action == "pivot.create":
                count = requested_pivot_count(self.instruction)
                if count is not None and len(self.valid_pivot_events()) < count:
                    return False
            elif action == "chart.create":
                count = requested_chart_count(self.instruction)
                if count > 0 and len(self.successful_action_events(action)) < count:
                    return False
            elif (
                action == "shape.format_text"
                and requested_matching_indent_without_bullet(self.instruction)
                is not None
            ):
                if not self.matching_indent_mutation_applied():
                    return False
            elif (
                action == "shape.write_text_native"
                and requested_content_textbox_insert(self.instruction) is not None
            ):
                if not self.content_textbox_mutation_applied():
                    return False
            elif action == "range.write" and requests_appended_named_rows(
                self.instruction
            ):
                if not self.requested_row_labels_satisfied():
                    return False
            elif action in {
                "range.merge",
                "range.write",
            } and requested_merged_text_regions(self.instruction):
                if not self.merged_text_mutations_satisfied():
                    return False
            elif not self.successful_action_events(
                action
            ) and not impress_semantics.satisfies_unexecuted_mutation(self, action):
                return False
        return True

    def required_mutation_actions(self) -> set[str]:
        return collect_required_mutation_actions(
            self,
            instruction_actions=instruction_required_actions,
            is_read_only_action=is_read_only,
            is_save_action=is_save,
        )

    def save_target_satisfied(self, action: str | None = None) -> bool:
        """Return true only when a current successful save proves the requested target."""
        files = [filename.lower() for filename in self.requested_save_files()]
        desktop_required = "desktop" in self.instruction.lower()
        for event in reversed(self.events):
            if not event.executed:
                continue
            if event.proposed.get("kind") == "gui":
                return False
            if event.proposed.get("kind") != "adapter":
                continue
            event_action = effective_canonical_action(event, self.domain)[1]
            if is_read_only(event_action):
                continue
            if not is_save(event_action):
                return False
            if action is not None:
                requested_action = canonical_action_request(self.domain, action, {})[1]
                if event_action != requested_action:
                    continue
            result = json.dumps(event.result, ensure_ascii=False, default=str).lower()
            if files and not all(filename in result for filename in files):
                continue
            if desktop_required and "/desktop/" not in result:
                continue
            return True
        return False

    def successful_action_events(self, action: str) -> list[ExecutionEvent]:
        requested_identity = canonical_action_request(self.domain, action, {})[:2]
        return [
            event
            for event in self.successful_adapter_events()
            if effective_canonical_action(event, self.domain)[:2] == requested_identity
        ]

    def requested_save_files(self) -> list[str]:
        if self.domain == "multi_apps":
            produced_files = self.successful_saved_output_files()
            if produced_files:
                return produced_files
        files = requested_files(self.instruction)
        action_set = set(self.recommended_actions) | set(
            instruction_required_actions(self.domain, self.instruction)
        )
        input_suffixes: set[str] = set()
        if self.domain == "libreoffice_impress" and "audio.insert" in action_set:
            input_suffixes.update({".mp3", ".wav", ".ogg", ".m4a"})
        if self.domain == "libreoffice_impress" and "shape.insert_image" in action_set:
            input_suffixes.update({".png", ".jpg", ".jpeg"})
        return [
            filename
            for filename in files
            if Path(filename).suffix.casefold() not in input_suffixes
        ]

    @staticmethod
    def _result_mappings(result: Any) -> list[dict[str, Any]]:
        mappings = []
        pending = [result]
        for _depth in range(8):
            if not pending:
                break
            next_pending = []
            for value in pending:
                if not isinstance(value, dict):
                    continue
                mappings.append(value)
                for key in (
                    "adapter_response",
                    "response",
                    "result",
                    "context_hint",
                    "downstream_context",
                ):
                    child = value.get(key)
                    if isinstance(child, dict):
                        next_pending.append(child)
            pending = next_pending
        return mappings

    def successful_chart_count(self) -> int:
        return len(self.successful_action_events("chart.create"))

    def successful_pivot_count(self) -> int:
        return len(self.valid_pivot_events())

    def successful_saved_output_files(self) -> list[str]:
        files = []
        for event in self.successful_adapter_events():
            action = effective_canonical_action(event, self.domain)[1]
            if not is_save(action) and not self.event_has_save_evidence(event):
                continue
            arguments = event.proposed.get("arguments", {})
            candidates = []
            if isinstance(arguments, dict):
                candidates.extend(
                    arguments.get(field) for field in ("output_path", "url")
                )
                payload = arguments.get("payload")
                params = payload.get("params") if isinstance(payload, dict) else None
                if isinstance(params, dict):
                    candidates.extend(
                        params.get(field) for field in ("output_path", "url")
                    )
            for body in self._result_mappings(event.result):
                candidates.extend(
                    body.get(field) for field in ("path", "url", "output_path")
                )
            for candidate in candidates:
                if not isinstance(candidate, str) or not candidate.strip():
                    continue
                parsed_path = (
                    unquote(urlparse(candidate).path)
                    if candidate.startswith("file:")
                    else candidate
                )
                filename = Path(parsed_path).name
                if filename and filename not in files:
                    files.append(filename)
        return files

    def latest_context_hint(self, action: str) -> dict[str, Any]:
        for event in reversed(self.successful_action_events(action)):
            if isinstance(event.result, dict) and isinstance(
                event.result.get("context_hint"), dict
            ):
                return event.result["context_hint"]
        return {}

    @staticmethod
    def event_has_verifier_evidence(event: ExecutionEvent) -> bool:
        return event.executed and has_passed_verification(event.result)

    def event_has_save_evidence(self, event: ExecutionEvent) -> bool:
        if not event.executed or not isinstance(event.result, dict):
            return False
        action = effective_canonical_action(event, self.domain)[1]
        event_verified = has_passed_verification(event.result)
        for result in RuntimeStateCoreMixin._result_mappings(event.result):
            saved = result.get("saved")
            if (
                isinstance(saved, dict)
                and saved.get("exists") is True
                and saved.get("valid") is True
            ):
                return True
            has_output = isinstance(result.get("path") or result.get("url"), str)
            size = result.get("size")
            if saved is True and has_output and isinstance(size, int) and size > 0:
                return True
            if is_save(action) and has_output and isinstance(size, int) and size > 0:
                return True
            output_path = result.get("output_path")
            output_bytes = result.get("output_bytes")
            output_sha256 = result.get("output_sha256")
            has_artifact_integrity = (
                isinstance(output_bytes, int)
                and not isinstance(output_bytes, bool)
                and output_bytes > 0
            ) or (
                isinstance(output_sha256, str)
                and re.fullmatch(r"[0-9a-fA-F]{64}", output_sha256) is not None
            )
            if (
                isinstance(output_path, str)
                and output_path.strip()
                and has_artifact_integrity
                and event_verified
            ):
                return True
        verification = event.result.get("verification")
        checks = verification.get("checks") if isinstance(verification, dict) else None
        return bool(
            isinstance(checks, list)
            and any(
                isinstance(check, dict)
                and check.get("type") == "file_saved"
                and check.get("passed") is True
                for check in checks
            )
        )

    def stage_read_satisfied(self, action: str) -> bool:
        """Track Calc source-read stages, not whether an observation may refresh."""
        if action == "range.read" and self.calc_used_range_read_covered():
            return True
        is_pivot_source_read = bool(
            action == "range.read"
            and re.search(r"(?i)\bpivot\b|数据透视", self.instruction)
        )
        if not is_pivot_source_read:
            return False

        if not self.pivot_count_satisfied():
            return bool(self.successful_action_events(action))

        latest_mutation_step = max(
            (
                event.step
                for event in self.events
                if event.executed
                and (
                    event.proposed.get("kind") == "gui"
                    or (
                        event.proposed.get("kind") == "adapter"
                        and not is_read_only(
                            effective_canonical_action(event, self.domain)[1]
                        )
                    )
                )
            ),
            default=0,
        )
        return any(
            event.step > latest_mutation_step
            and event.executed
            and event.proposed.get("kind") == "adapter"
            and effective_canonical_action(event, self.domain)[:2]
            == canonical_action_request(self.domain, action, {})[:2]
            for event in self.events
        )
