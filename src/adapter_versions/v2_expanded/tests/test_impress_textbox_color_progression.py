from __future__ import annotations

from types import SimpleNamespace

from integrations.lite_agent.action_selection import ActionSelectionMixin
from integrations.lite_agent.impress_textboxes import stage_actions
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


INSTRUCTION = (
    "Navigate to slide 5 and set the font color of all textboxes to yellow. "
    "Use exactly 'yellow'—no variations such as light yellow, dark yellow, or any "
    "other color."
)
INSPECT_ACTION = "presentation.inspect"
FORMAT_ACTION = "slide.format_text_roles"
ACTIONS = [INSPECT_ACTION, FORMAT_ACTION, "presentation.save"]


def _event(step: int, action: str, arguments: dict) -> ExecutionEvent:
    return ExecutionEvent(
        step=step,
        timestamp_utc="2026-09-20T00:00:00Z",
        proposed={"kind": "adapter", "action": action, "arguments": arguments},
        executed=True,
        result={"status": "ok"},
    )


def _state(events: list[ExecutionEvent]) -> RuntimeState:
    return RuntimeState(
        task_id="synthetic-all-textbox-color",
        domain="libreoffice_impress",
        instruction=INSTRUCTION,
        events=events,
    )


def test_all_textbox_color_stages_inspection_then_required_mutation() -> None:
    state = _state([])
    assert stage_actions(state, ACTIONS) == [INSPECT_ACTION]

    state.events.append(_event(1, INSPECT_ACTION, {"slides": [4]}))
    assert stage_actions(state, ACTIONS) == [FORMAT_ACTION]

    state.events.append(
        _event(2, FORMAT_ACTION, {"slide": 4, "roles": ["all"], "color": "red"})
    )
    assert stage_actions(state, ACTIONS) == [FORMAT_ACTION]

    state.events.append(
        _event(
            3,
            FORMAT_ACTION,
            {"slide": 4, "roles": ["all"], "color": "yellow"},
        )
    )
    assert stage_actions(state, ACTIONS) == ACTIONS


def test_all_textbox_color_progression_is_wired_into_action_selection() -> None:
    selector = ActionSelectionMixin()
    selector.config = SimpleNamespace(top_k_actions=7)
    state = _state([_event(1, INSPECT_ACTION, {"slides": [4]})])

    assert selector.selected_actions(state) == [FORMAT_ACTION]
