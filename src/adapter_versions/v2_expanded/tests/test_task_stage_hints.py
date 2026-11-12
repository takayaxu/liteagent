"""The authorized experiment must leave every other task's prompts unchanged."""
import io
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.task_stage_hints import PROFILE, SALES, model_hint


def test_profile_is_opt_in_and_exact_task_and_domain_scoped():
    state = RuntimeState(SALES, "libreoffice_calc", "Calculate total sales and growth.")
    assert model_hint(None, state) is None
    assert model_hint("unknown", state) is None
    assert model_hint(PROFILE, state).startswith("OBSERVE:")
    assert model_hint(PROFILE, replace(state, domain="multi_apps")) is None
    root = Path(__file__).resolve().parents[4]
    tasks = json.loads((root / "configs/single-task-local9b-thinking.json").read_text())["tasks"]
    for task in tasks:
        if task["task_id"] != SALES:
            other = replace(state, task_id=task["task_id"], domain=task["domain"])
            assert model_hint(PROFILE, other) is None


def test_actual_messages_remain_identical_for_other_task_and_hide_identity():
    config = LiteAgentConfig(base_url="http://unused", include_gui=False)
    agent = LiteAgent(config, object(), model_client=SimpleNamespace(client=object()))
    state = RuntimeState("unrelated", "libreoffice_calc", "Calculate total sales and growth.")
    out = io.BytesIO()
    Image.new("RGB", (20, 20)).save(out, format="PNG")
    before = agent._messages(state, out.getvalue(), tools=[])
    agent.config = replace(config, task_stage_hints=PROFILE)
    assert agent._messages(state, out.getvalue(), tools=[]) == before
    state.task_id = SALES
    messages = agent._messages(state, out.getvalue(), tools=[])
    assert "user-authorized stage guidance" in messages[0]["content"]
    agent.assert_agent_surface_safe(state, messages, [])
    assert SALES not in json.dumps(messages)


def test_failed_observation_does_not_advance_stage():
    state = RuntimeState(SALES, "libreoffice_calc", "Calculate total sales and growth.")
    event = ExecutionEvent(1, "", {"action": "workbook.inspect"}, executed=False)
    state.events.append(event)
    assert "inspect the open workbook" in model_hint(PROFILE, state)
    event.executed = True
    assert "read the observed source range" in model_hint(PROFILE, state)
