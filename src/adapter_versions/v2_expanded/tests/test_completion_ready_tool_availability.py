"""Structural completion evidence must preserve further model investigation."""
from copy import deepcopy
import json
from types import SimpleNamespace

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


def worker():
    class NoExecution:
        def execute(self, *_args):
            raise AssertionError("Tool selection must not execute application changes")
    return LiteAgent(
        LiteAgentConfig(base_url="http://unused/v1", include_gui=False),
        NoExecution(), model_client=SimpleNamespace(client=object()),
    )


def ready_state():
    routes = [("vs_code", "file.read_text"), ("vs_code", "file.replace_literal")]
    search = ExecutionEvent(
        step=1, timestamp_utc="2030-01-01T00:00:00Z", executed=True,
        proposed={"kind": "catalog", "tool": "tools_search", "arguments": {"query": "edit source text"}},
        result={"status": "ok", "matches": [
            {"action": "adapter.call", "adapter": owner, "downstream_action": action}
            for owner, action in routes
        ]},
    )
    edit = ExecutionEvent(
        step=2, timestamp_utc="2030-01-01T00:00:00Z", parsed=True, validated=True, executed=True,
        proposed={"kind": "adapter", "tool": "adapter__adapter_call", "action": "adapter.call",
                  "arguments": {"adapter": "vs_code", "action": "file.replace_literal",
                                "payload": {"params": {"path": "/tmp/calculator.py", "old": "x", "new": "y"}}}},
        result={"status": "ok", "verification": {"passed": True}},
    )
    return RuntimeState(task_id="synthetic-investigation", domain="multi_apps",
                        instruction="Correct the calculation in the source file.", events=[search, edit])


def test_structural_readiness_keeps_search_and_application_routes():
    current, agent = ready_state(), worker()
    assert agent._generic_completion_gate(current)["passed"]
    before = deepcopy(current.events)
    names = {t["function"]["name"] for t in agent.tools(current)}
    assert {"tools_search", "adapter__adapter_call", "propose_done", "fail_task", "completion_revise"} <= names
    assert current.events == before and not current.done


def test_optional_revision_still_blocks_another_completion_claim():
    current, agent = ready_state(), worker()
    result = agent.execute_proposal(current, {
        "tool": "completion_revise", "_model_visible_tools": agent.tools(current),
        "arguments_raw": json.dumps({"observed": "The result differs from the requested calculation.",
                                      "required": "Correct calculation.", "correction": "Correct the expression."}),
    })
    assert result.executed, result.error
    assert not agent._generic_completion_gate(current)["passed"]
