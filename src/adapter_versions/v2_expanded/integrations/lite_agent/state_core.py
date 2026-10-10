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
from .request_blocks import request_block_is_stale


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
            return summary[:limit] if limit > 0 else []
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

    def filesystem_observation_state(self) -> dict[str, Any] | None:
        """Return the completed discovery phase for a file-organization task.

        The marker is derived only from a successful, bounded ``kind=any``
        result.  It deliberately carries exact observed paths so the next
        phase can classify and rename those objects without searching again.
        """
        if self.domain != "multi_apps" or not re.search(
            r"(?i)\b(?:organize|organization|categorize|classify|place|put|move|relocate)\b",
            self.instruction,
        ):
            return None
        for event in reversed(self.successful_adapter_events()):
            domain, action, arguments = effective_canonical_action(event, self.domain)
            if (domain, action) != ("os", "filesystem.find"):
                continue
            params = arguments.get("params", arguments) if isinstance(arguments, dict) else {}
            if not isinstance(params, dict) or params.get("kind") != "any":
                continue
            marker: dict[str, Any] | None = None
            for body in self._result_mappings(event.result):
                nested = body.get("downstream_context")
                candidate = nested if isinstance(nested, dict) else body
                if not isinstance(candidate.get("matches"), list):
                    continue
                if candidate.get("truncated") is True:
                    continue
                matches = [
                    {
                        key: item.get(key)
                        for key in ("path", "name", "kind")
                        if key in item
                    }
                    for item in candidate["matches"]
                    if isinstance(item, dict) and isinstance(item.get("path"), str)
                ]
                roots = params.get("roots")
                root_list = [str(root) for root in roots] if isinstance(roots, list) else []
                marker = {
                    "complete": True,
                    "observed_roots": root_list,
                    "observed_entries": matches,
                    "next_required_phase": "classify_and_move",
                    "next_required_actions": [
                        "read content only for ambiguous files",
                        "filesystem.rename each observed source to its category folder",
                    ],
                    "classification_policy": [
                        "Paper_reading: only files whose observed content is an academic or research paper",
                        "Projects: directories or files that are clearly coding projects with source code",
                        "Miscellaneous: every other file, including presentations, spreadsheets, forms, and policy PDFs",
                    ],
                    "content_evidence_required": (
                        "Do not classify a PDF as a paper from its extension or filename; use the observed text."
                    ),
                    "forbidden_next_action": "repeat filesystem.find for an observed root",
                }
                break
            if marker is not None:
                return marker
        return None

    def filesystem_organization_pending_entries(self) -> list[str]:
        """Return observed source paths that have not been renamed yet."""
        marker = self.filesystem_observation_state()
        if not isinstance(marker, dict) or marker.get("complete") is not True:
            return []
        destinations = {"Paper_reading", "Projects", "Miscellaneous"}
        observed = {
            str(item.get("path"))
            for item in marker.get("observed_entries", [])
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and item.get("path")
            and item["path"].rstrip("/").rsplit("/", 1)[-1] not in destinations
        }
        moved: set[str] = set()
        for event in self.successful_adapter_events():
            domain, action, arguments = effective_canonical_action(event, self.domain)
            if (domain, action) != ("os", "filesystem.rename"):
                continue
            source = arguments.get("source") if isinstance(arguments, dict) else None
            if isinstance(source, str):
                moved.add(source.rstrip("/"))
        return sorted(path for path in observed if path.rstrip("/") not in moved)

    def filesystem_organization_complete(self) -> bool:
        marker = self.filesystem_observation_state()
        return bool(
            isinstance(marker, dict)
            and marker.get("complete") is True
            and not self.filesystem_organization_pending_entries()
        )

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
            route = block.get("downstream_route")
            if (
                isinstance(route, dict)
                and isinstance(route.get("adapter"), str)
                and isinstance(route.get("action"), str)
            ):
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
        read_only_variants: dict[str, set[str]] = {}
        for block in self.active_request_blocks().values():
            action = block["action"]
            schema = DIRECT_ACTION_SCHEMAS.get(self.domain, {}).get(action)
            if schema is not None and not schema.get("properties"):
                blocked.add(action)
            elif is_read_only(action):
                read_only_variants.setdefault(action, set()).add(
                    block["argument_signature"]
                )
        blocked.update(
            action
            for action, variants in read_only_variants.items()
            if len(variants) >= 2
        )
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
