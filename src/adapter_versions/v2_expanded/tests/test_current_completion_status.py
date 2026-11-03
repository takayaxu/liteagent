"""Current claim eligibility must survive compact recovery after old errors."""
from copy import deepcopy
import json

import pytest

from integrations.lite_agent.state_model import ExecutionEvent
from test_completion_outcomes import state, agent, event


def status(messages):
    for message in messages:
        parts = message.get("content", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            text = part.get("text", "")
            if "current_completion_status:\n" in text:
                return json.JSONDecoder().raw_decode(text.split("current_completion_status:\n", 1)[1])[0]
    return None


@pytest.mark.parametrize("mode", ["normal", "protocol", "execution"])
def test_old_missing_items_cannot_hide_current_readiness_or_new_mutation(mode):
    current = state()
    current.events.insert(0, ExecutionEvent(
        step=0, timestamp_utc="", proposed={"kind": "completion", "tool": "propose_done"},
        parsed=True, validated=True, executed=False,
        error={"status": "rejected", "missing": ["OLD unsaved table"]},
    ))
    worker = agent()
    kwargs = {"protocol_recovery": mode == "protocol", "execution_recovery": mode == "execution"}
    before = deepcopy(current.events)
    result = status(worker._messages(current, b"image", tools=worker.tools(current), **kwargs))
    assert result["structural_gate_passed"] is True and result["missing"] == []
    assert not current.done and current.events == before
    current.events.append(event(11, "range.write", {"sheet": "Summary", "range": "H3", "values": [["Changed"]]}))
    result = status(worker._messages(current, b"image", tools=worker.tools(current), **kwargs))
    assert result["structural_gate_passed"] is False and result["missing"]
    assert "historical" in result["meaning"]


def test_no_old_rejected_claim_adds_no_completion_status():
    current = state()
    worker = agent()
    assert status(worker._messages(current, b"image", tools=worker.tools(current))) is None
