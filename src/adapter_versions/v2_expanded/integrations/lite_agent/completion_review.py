"""Model-owned completion review and explicit return to correction."""

from typing import Any

from .completion_policy import (
    action_is_read_only,
    action_is_save,
    command_is_read_only,
    effective_canonical_action,
)


TOOL_NAME = "completion_revise"


def unresolved_discrepancy(state: Any) -> dict[str, Any] | None:
    """A failed self-review cannot be erased by another read or success claim."""
    for event in reversed(state.events):
        if not event.executed or event.error:
            continue
        if event.proposed.get("tool") == TOOL_NAME:
            return event.proposed.get("arguments", {})
        if event.proposed.get("kind") == "gui":
            return None
        if event.proposed.get("kind") == "adapter":
            _domain, action, arguments = effective_canonical_action(event, state.domain)
            if not (action_is_read_only(action) or action_is_save(action)
                    or command_is_read_only(action, arguments)):
                return None
    return None


def review_ready(state: Any, gate: dict[str, Any]) -> bool:
    if gate.get("passed") is not True:
        return False
    for event in reversed(state.events):
        if not event.executed or event.error:
            continue
        if event.proposed.get("tool") == TOOL_NAME:
            # A model-observed discrepancy keeps correction open until an
            # actual change occurs, even if the old structural gate passes.
            return False
        if event.proposed.get("kind") == "gui":
            return True
        if event.proposed.get("kind") == "adapter":
            _domain, action, arguments = effective_canonical_action(event, state.domain)
            if not (
                action_is_read_only(action)
                or action_is_save(action)
                or command_is_read_only(action, arguments)
            ):
                return True
    return False


def revision_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Return from completion review to correction only when the observed "
                "result differs from a user requirement. Quote the observation and "
                "requirement and describe the needed correction. This changes no "
                "application state and does not complete the task. Do not request "
                "correction merely to repeat an already satisfied inspection."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    name: {"type": "string", "minLength": 1}
                    for name in ("observed", "required", "correction")
                },
                "required": ["observed", "required", "correction"],
                "additionalProperties": False,
            },
        },
    }
