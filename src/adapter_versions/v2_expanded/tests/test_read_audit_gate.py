"""Read review owns a runtime lease, independently of phase and handoff audits."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent import read_audit_gate
from integrations.lite_agent.episode_control import record_model_audit
from integrations.lite_agent.state_model import RuntimeState
from integrations.lite_agent.tool_catalog import build_tools


class Executor:
    def __init__(self):
        self.calls = []
        self.succeed = True

    def execute(self, domain, action, arguments, *args):
        self.calls.append((action, deepcopy(arguments)))
        return {"executed": self.succeed, "result": {"context_hint": {
            "sheet": arguments.get("sheet"), "range": arguments.get("range"),
            "display_text": [["Year", "Balance"], ["2020", "100"]],
        }}, "error": None if self.succeed else {"type": "ReadError"}}


def setup(enabled=True, domain="libreoffice_calc"):
    executor = Executor()
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused/v1", include_gui=False,
                                    read_audit_gate=enabled), executor,
                      model_client=SimpleNamespace(client=object()))
    state = RuntimeState(task_id="synthetic-read-review", domain=domain,
                         instruction="Read the two requested columns and report their values.")
    return agent, state, executor


def call(agent, state, tool, args, tools=None):
    return agent.execute_proposal(state, {"tool": tool, "arguments_raw": json.dumps(args),
        "_model_visible_tools": tools if tools is not None else agent.tools(state)})


def read(agent, state):
    return call(agent, state, "adapter__range_read", {"sheet": "Input", "range": "A1:B2"},
                build_tools(state.domain, ["range.read"], include_gui=False))


def verdict(state, sufficient=False):
    return {"event_step": state.read_audit["event_step"],
            "verdict": "sufficient" if sufficient else "insufficient",
            "reason": "Evidence covers the request" if sufficient else "Missing second column",
            "missing_evidence": [] if sufficient else ["second column values"],
            "next_action": "continue" if sufficient else "range.read",
            "next_arguments_json": "{}" if sufficient else '{"sheet":"Input","range":"A1:B2"}'}


def names(agent, state):
    return {t["function"]["name"] for t in agent.tools(state)}


def test_read_forces_review_and_repair_overrides_stage_filters_then_reaudits():
    agent, state, executor = setup()
    first = read(agent, state)
    assert first.executed, first.error
    assert names(agent, state) == {"read_audit"}
    review = call(agent, state, "read_audit", verdict(state))
    assert review.executed, review.error
    assert state.read_audit["status"] == "repair_pending"
    assert {"adapter__range_read", "adapter__workbook_inspect"} <= names(agent, state)
    assert "propose_done" not in names(agent, state)
    repaired = call(agent, state, "adapter__range_read", {"sheet": "Input", "range": "A1:B2"})
    assert repaired.executed, repaired.error
    assert state.read_audit == {"status": "review_pending", "event_step": repaired.step}
    accepted = call(agent, state, "read_audit", verdict(state, True))
    assert accepted.executed, accepted.error
    assert state.read_audit["status"] == "passed"
    assert "read_audit" not in names(agent, state)
    assert len(executor.calls) == 2


@pytest.mark.parametrize("patch", [
    {"event_step": 999}, {"missing_evidence": []},
    {"next_arguments_json": "[]"}, {"next_arguments_json": '{"invented":1}'},
    {"verdict": "sufficient"}, {"missing_evidence": "none"},
])
def test_invalid_review_never_consumes_pending_state(patch):
    agent, state, _ = setup()
    assert read(agent, state).executed
    expected = deepcopy(state.read_audit)
    args = verdict(state)
    args.update(patch)
    result = call(agent, state, "read_audit", args)
    assert not result.executed
    assert state.read_audit == expected
    assert names(agent, state) == {"read_audit"}


@pytest.mark.parametrize("repair", [False, True])
def test_execution_and_completion_cannot_bypass_gate_even_with_forged_surface(repair):
    agent, state, executor = setup()
    assert read(agent, state).executed
    if repair:
        assert call(agent, state, "read_audit", verdict(state)).executed
    for action, args in [("range.write", {"sheet": "Input", "range": "C1", "values": [[1]]})]:
        surface = build_tools(state.domain, [action], include_gui=False)
        result = call(agent, state, "adapter__range_write", args, surface)
        assert not result.executed
    assert len(executor.calls) == 1
    assert not agent._generic_completion_gate(state)["passed"]
    result = call(agent, state, "propose_done", {"reason": "Finished", "evidence": ["read"]},
                  build_tools(state.domain, [], include_gui=False))
    assert not result.executed and not state.done


def test_failed_repair_read_and_handoff_do_not_discharge_read_review():
    agent, state, executor = setup()
    first = read(agent, state)
    state.pending_model_audit = {"event_step": first.step, "tool": "adapter__range_read"}
    record_model_audit(state, {"tool": "read_audit"})
    assert names(agent, state) == {"read_audit"}
    assert call(agent, state, "read_audit", verdict(state)).executed
    expected = deepcopy(state.read_audit)
    executor.succeed = False
    assert not call(agent, state, "adapter__range_read", {"sheet": "Input", "range": "A1:B2"}).executed
    assert state.read_audit == expected
    executor.succeed = True
    result = call(agent, state, "adapter__workbook_inspect", {})
    assert result.executed, result.error
    assert state.read_audit == expected


def test_off_switch_and_non_calc_are_unchanged_and_text_review_has_real_evidence():
    agent, state, _ = setup(False)
    assert read(agent, state).executed
    assert state.read_audit is None
    agent, state, _ = setup(domain="os")
    state.read_audit = {"status": "review_pending", "event_step": 1}
    assert read_audit_gate.gate_tools(agent, state) is None
    agent, state, _ = setup()
    assert read(agent, state).executed
    pending = deepcopy(state.read_audit)
    messages = agent._messages(state, b"not-an-image")
    agent.assert_agent_surface_safe(state, messages, agent.tools(state))
    assert "display_text" in messages[-1]["content"]
    assert "image_url" not in json.dumps(messages)
    assert state.read_audit == pending
