"""The authorized experiment must leave every other task's prompts unchanged."""
import io
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.task_stage_hints import PROFILE, model_hint as scoped_model_hint

SALES = "0326d92d-d218-48a8-9ca1-981cd6d064c7"
TARGETS = {SALES: "sales-growth"}


def model_hint(profile, state):
    return scoped_model_hint(profile, state, targets=TARGETS)


def test_profile_is_opt_in_and_exact_task_and_domain_scoped():
    state = RuntimeState(SALES, "libreoffice_calc", "Calculate total sales and growth.")
    assert model_hint(None, state) is None
    assert model_hint("unknown", state) is None
    assert scoped_model_hint(PROFILE, state) is None
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
    agent.config = replace(config, task_stage_hints=PROFILE, task_stage_hint_targets=TARGETS)
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


def test_live_anchors_use_current_observation_and_flat_label_writes():
    from integrations.lite_agent.task_stage_hints import _sales_anchors
    state = RuntimeState(SALES, "libreoffice_calc", "Calculate total sales and growth.")
    state.events = [
        ExecutionEvent(1, "", {"action": "range.read"}, executed=True,
                       result={"cell_addresses": [["D4", "E4"]],
                               "display_text": [["Jan", "Feb"]]}),
        ExecutionEvent(2, "", {"action": "range.write", "arguments":
                       {"range": "C20", "values": ["Total"]}}, executed=True),
        ExecutionEvent(3, "", {"action": "range.write", "arguments":
                       {"range": "C21", "values": [["Growth"]]}}, executed=True),
    ]
    anchors = json.loads(_sales_anchors(state))
    assert anchors["Jan_growth_cell_must_be_blank"] == "D21"
    assert anchors["Feb_formula_from_observed_Total_row"] == "=(E20-D20)/D20"


def test_full_queue_configuration_cannot_activate_hints_for_other_173_tasks():
    root = Path(__file__).resolve().parents[4]
    config = json.loads((root / "configs/single-task-deadline-stage-hints.json").read_text())
    targets = config["protocol"]["task_stage_hint_targets"]
    assert len(targets) == 16
    matched = []
    for task in config["tasks"]:
        state = RuntimeState(task["task_id"], task["domain"], "Calculate total sales and growth.")
        assert scoped_model_hint(None, state, targets=targets) is None
        if state.task_id in targets:
            matched.append(state.task_id)
        else:
            assert scoped_model_hint(PROFILE, state, targets=targets) is None
    assert set(matched) == set(targets)


def test_vowel_grouping_reads_first_character_and_preserves_empty_cells():
    from integrations.lite_agent.task_stage_hints import _vowel_hint
    state = RuntimeState("synthetic", "libreoffice_writer", "Color vowel-initial words.")
    state.events = [ExecutionEvent(1, "", {"action": "table.read"}, executed=True,
        result={"cell_fields": ["name", "text", "font_color"],
                "cells": [["A1", "eat", "automatic"], ["A2", "yes", "automatic"],
                          ["B1", "white", "automatic"], ["B2", "", "automatic"]]})]
    hint = _vowel_hint(state)
    assert '"word": "eat", "first_letter": "e"' in hint
    assert '"word": "yes", "first_letter": "y"' in hint
    assert '"cell": "B2"' not in hint


def test_gemini_extraction_moves_to_document_creation_only_after_success():
    from integrations.lite_agent.task_stage_hints import _cross_app_hint
    state = RuntimeState("synthetic", "multi_apps", "Copy all Gemini responses into Word.")
    command = ExecutionEvent(1, "", {"tool": "adapter__adapter_call", "action": "adapter.call",
        "arguments": {"adapter": "os", "action": "command.run", "payload": {"params": {
            "argv": ["python3", "-c", "def walk(x): pass\nopen('/tmp/gemini-responses.txt','w')"],
            "provenance": "shell_history"}}}}, executed=False, error={"message": "bad argv"})
    state.events = [command]
    assert "already SUCCEEDED" not in _cross_app_hint(state, "gemini-document")
    command.executed = True
    command.error = None
    assert "create Desktop/gemini_results.docx once" in _cross_app_hint(state, "gemini-document")
