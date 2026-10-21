"""Lifecycle rules for repeated-request blocks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .completion_policy import (
    action_is_read_only,
    action_is_save,
    effective_canonical_action,
)

if TYPE_CHECKING:
    from .state_model import ExecutionEvent


_TOOLS_SEARCH_PROVENANCE_ERROR = (
    "requires a matching public tools_search result before execution"
)


def is_tools_search_provenance_error(error: object) -> bool:
    """Return whether an error only says that catalog provenance is missing."""

    if not isinstance(error, dict):
        return False
    detail = error.get("detail") or error.get("message")
    return (
        isinstance(detail, str)
        and _TOOLS_SEARCH_PROVENANCE_ERROR.casefold() in detail.casefold()
    )


def _catalog_contains_route(event: object, route: tuple[str, str]) -> bool:
    if not getattr(event, "executed", False):
        return False
    proposed = getattr(event, "proposed", None)
    if not isinstance(proposed, dict) or proposed.get("kind") != "catalog":
        return False
    result = getattr(event, "result", None)
    matches = result.get("matches") if isinstance(result, dict) else None
    if not isinstance(matches, list):
        return False
    return any(
        isinstance(match, dict)
        and match.get("action") == "adapter.call"
        and match.get("adapter") == route[0]
        and match.get("downstream_action") == route[1]
        for match in matches
    )


def event_changes_application_state(event: ExecutionEvent) -> bool:
    """Return whether a successful event can make an earlier request valid again."""

    if not event.executed:
        return False
    kind = event.proposed.get("kind")
    if kind == "gui":
        return True
    if kind != "adapter":
        return False
    _domain, action, _arguments = effective_canonical_action(event, "")
    # An image export creates a new external artifact. It must invalidate a
    # prior failed request that was caused only by that artifact being absent,
    # even though the generic ``.export`` suffix is otherwise treated like a
    # save operation.
    if action == "shape.export_image":
        return True
    return bool(
        isinstance(action, str)
        and action
        and not action_is_read_only(action)
        and not action_is_save(action)
    )


def request_block_is_stale(
    events: list[ExecutionEvent], *, blocked_at_step: int
) -> bool:
    """Expire a request block after a later successful application mutation."""

    blocked_event = next(
        (event for event in events if event.step == blocked_at_step), None
    )
    blocked_error = getattr(blocked_event, "error", None)
    blocked_proposal = getattr(blocked_event, "proposed", None)
    if (
        isinstance(blocked_proposal, dict)
        and blocked_proposal.get("action") == "adapter.call"
        and is_tools_search_provenance_error(
            blocked_error.get("previous_error")
            if isinstance(blocked_error, dict)
            else None
        )
    ):
        arguments = blocked_proposal.get("arguments")
        route = (
            arguments.get("adapter"),
            arguments.get("action"),
        ) if isinstance(arguments, dict) else (None, None)
        if all(isinstance(item, str) for item in route):
            if any(
                event.step > blocked_at_step
                and _catalog_contains_route(event, route)  # type: ignore[arg-type]
                for event in events
            ):
                return True

    return any(
        event.step > blocked_at_step and event_changes_application_state(event)
        for event in events
    )
