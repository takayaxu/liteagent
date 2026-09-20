from __future__ import annotations

from types import SimpleNamespace

import jsonschema
import pytest

from impress_adapter import uno_worker
from impress_adapter.errors import AdapterError
from impress_adapter.schema import parse_action_request
from impress_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
from integrations.lite_agent.impress_role_text_update import (
    role_text_update_argument_contract_errors,
    role_text_update_requirement_errors,
    stage_actions,
)
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.tool_catalog import DIRECT_ACTION_SCHEMAS, build_tools


TEXT_ACTION = "slide.set_role_text"
FORMAT_ACTION = "slide.format_text_roles"
INSTRUCTION = 'Give slide 3 the center aligned title, "Summary".'


class NativeText:
    def __init__(self, value: str, *, accept_write: bool = True):
        self.value = value
        self.accept_write = accept_write

    def getString(self) -> str:
        return self.value

    def setString(self, value: str) -> None:
        if self.accept_write:
            self.value = value


def _event(step: int, action: str, arguments: dict, result: dict) -> ExecutionEvent:
    return ExecutionEvent(
        step=step,
        timestamp_utc="2026-09-20T00:00:00Z",
        proposed={"kind": "adapter", "action": action, "arguments": arguments},
        executed=True,
        result=result,
    )


def _state(events: list[ExecutionEvent]) -> RuntimeState:
    return RuntimeState(
        task_id="synthetic-role-text-split",
        domain="libreoffice_impress",
        instruction=INSTRUCTION,
        events=events,
    )


def _inspect() -> ExecutionEvent:
    return _event(1, "presentation.inspect", {}, {"status": "ok"})


def _text_event() -> ExecutionEvent:
    return _event(
        2,
        TEXT_ACTION,
        {"slide": 2, "role": "title", "text": "Summary"},
        {
            "status": "ok",
            "result": {
                "slide": 2,
                "requested_role": "title",
                "resolved_role": "title",
                "path": [0],
                "previous_text": "Old",
                "text": "Summary",
            },
        },
    )


def _format_event() -> ExecutionEvent:
    return _event(
        3,
        FORMAT_ACTION,
        {"slide": 2, "roles": ["title"], "alignment": "center"},
        {
            "status": "ok",
            "result": {
                "slide": 2,
                "rules": [
                    {
                        "requested_roles": ["title"],
                        "normalized_roles": ["title"],
                        "formatted": [
                            {
                                "path": [0],
                                "role": "title",
                                "text": "Summary",
                                "properties": {"ParaAdjust": "3"},
                            }
                        ],
                    }
                ],
            },
        },
    )


def test_set_role_text_public_and_runtime_contract_is_text_only() -> None:
    manifest = STRICT_ACTION_PARAM_SCHEMAS[TEXT_ACTION]
    assert DIRECT_ACTION_SCHEMAS["libreoffice_impress"][TEXT_ACTION] == manifest
    exposed = build_tools(
        "libreoffice_impress",
        [TEXT_ACTION],
        include_gui=False,
        include_control_tools=False,
        strict_generic=True,
    )[0]["function"]["parameters"]
    assert set(exposed["properties"]) == {"slide", "role", "text"}
    valid = {"slide": 2, "role": "title", "text": "Summary"}
    jsonschema.validate(valid, exposed)
    assert (
        parse_action_request({"action": TEXT_ACTION, "params": valid}).params == valid
    )

    combined = {**valid, "alignment": "center"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(combined, exposed)
    with pytest.raises(
        AdapterError, match="formatting fields.*slide.format_text_roles"
    ):
        parse_action_request({"action": TEXT_ACTION, "params": combined})


def test_set_role_text_replaces_and_verifies_only_text(monkeypatch) -> None:
    text = NativeText("Old")
    shape = SimpleNamespace(getText=lambda: text)
    monkeypatch.setattr(
        uno_worker,
        "iter_shapes_for_roles",
        lambda _page, _roles: iter([([0], shape, "title")]),
    )
    result = uno_worker._set_role_text(
        SimpleNamespace(page=lambda _index: object()),
        {"slide": 2, "role": "title", "text": "Summary"},
    )
    assert result == {
        "slide": 2,
        "requested_role": "title",
        "resolved_role": "title",
        "path": [0],
        "previous_text": "Old",
        "text": "Summary",
    }


def test_set_role_text_readback_failure_reports_observed_state(monkeypatch) -> None:
    text = NativeText("Old", accept_write=False)
    shape = SimpleNamespace(getText=lambda: text)
    monkeypatch.setattr(
        uno_worker,
        "iter_shapes_for_roles",
        lambda _page, _roles: iter([([0], shape, "title")]),
    )
    with pytest.raises(AdapterError) as failure:
        uno_worker._set_role_text(
            SimpleNamespace(page=lambda _index: object()),
            {"slide": 2, "role": "title", "text": "Summary"},
        )
    assert failure.value.code == "VERIFICATION_FAILED"
    assert failure.value.details == {
        "expected": "Summary",
        "observed": "Old",
        "path": [0],
    }


def test_role_text_workflow_requires_two_separate_confirmed_mutations() -> None:
    actions = ["presentation.inspect", TEXT_ACTION, FORMAT_ACTION, "presentation.save"]
    state = _state([])
    assert stage_actions(state, actions) == ["presentation.inspect"]

    state.events.append(_inspect())
    assert stage_actions(state, actions) == [TEXT_ACTION]
    combined = {"slide": 2, "role": "title", "text": "Summary", "alignment": "center"}
    assert role_text_update_argument_contract_errors(state, TEXT_ACTION, combined)

    state.events.append(_text_event())
    assert stage_actions(state, actions) == [FORMAT_ACTION]
    assert role_text_update_requirement_errors(state) == [
        "slide.format_text_roles lacks Adapter-confirmed coverage for the formatting "
        "explicitly requested with the semantic-role text replacement"
    ]
    valid_format = {"slide": 2, "roles": ["title"], "alignment": "center"}
    assert not role_text_update_argument_contract_errors(
        state, FORMAT_ACTION, valid_format
    )

    state.events.append(_format_event())
    assert stage_actions(state, actions) == actions
    assert role_text_update_requirement_errors(state) == []
