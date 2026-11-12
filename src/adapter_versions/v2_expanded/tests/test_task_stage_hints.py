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


def test_gemini_extraction_example_keeps_all_responses_in_nested_source_order(tmp_path):
    from integrations.lite_agent.task_stage_hints import _cross_app_hint
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"1": {"first": {"Gemini": "No keyword\nstill retain"},
        "second": [{"GPT3": "omit", "gemini": "Iliad response"}]}}))
    state = RuntimeState("synthetic", "multi_apps", "Copy all Gemini responses into Word.")
    state.events = [ExecutionEvent(1, "", {"tool": "adapter__adapter_call", "action": "adapter.call",
        "arguments": {"adapter": "vs_code", "action": "file.read_text",
            "payload": {"params": {"path": str(source)}}}}, executed=True,
        result={"path": str(source)})]
    hint = _cross_app_hint(state, "gemini-document")
    call = json.loads(hint[hint.index('{"adapter"'):])
    params = call["payload"]["params"]
    assert len(params["argv"]) == 3
    assert params["cwd_source"] == "home" and params["provenance"] == "shell_history"
    output = tmp_path / "extracted.txt"
    script = params["argv"][2].replace("/tmp/gemini-responses.txt", str(output))
    exec(compile(script, "source-based-extraction-example", "exec"), {})
    assert output.read_text() == "No keyword still retain\n\nIliad response"


def test_full_queue_other_173_actual_messages_are_unchanged(monkeypatch):
    import integrations.lite_agent.task_stage_hints as hints
    root = Path(__file__).resolve().parents[4]
    config = json.loads((root / "configs/single-task-deadline-stage-hints.json").read_text())
    targets = config["protocol"]["task_stage_hint_targets"]
    basic = LiteAgentConfig(base_url="http://unused", include_gui=False)
    agent = LiteAgent(basic, object(), model_client=SimpleNamespace(client=object()))
    out = io.BytesIO()
    Image.new("RGB", (20, 20)).save(out, format="PNG")
    def unexpected_ocr(_):
        raise AssertionError("Single-task OCR must never run for an unrelated task")
    monkeypatch.setattr(hints, "gemini_gui_observations", unexpected_ocr)
    checked = 0
    for task in config["tasks"]:
        if task["task_id"] in targets:
            continue
        source = root / "src/third_party/OSWorld/evaluation_examples/examples" / task["domain"] / (task["task_id"] + ".json")
        state = RuntimeState(task["task_id"], task["domain"], json.loads(source.read_text())["instruction"])
        agent.config = basic
        before = agent._messages(state, out.getvalue(), tools=[])
        agent.config = replace(basic, task_stage_hints=PROFILE, task_stage_hint_targets=targets)
        assert agent._messages(state, out.getvalue(), tools=[]) == before
        checked += 1
    assert checked == 173


def test_gemini_selected_text_advances_to_close_marker_then_native_verification(monkeypatch):
    import integrations.lite_agent.task_stage_hints as hints
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=True,
        task_stage_hints=PROFILE, task_stage_hint_targets={"synthetic": "gemini-document"}),
        object(), model_client=SimpleNamespace(client=object()))
    state = RuntimeState("synthetic", "multi_apps", "Copy all Gemini values and highlight Iliad.")
    state.events = [ExecutionEvent(i, "", {"action": "adapter.call", "arguments": {
        "adapter": "libreoffice_writer", "action": action, "payload": {"params": {}}}}, executed=True)
        for i, action in enumerate(("document.create", "document.append_text_file"), 1)]
    state.events.append(ExecutionEvent(3, "", {"action": "adapter.call", "arguments": {
        "adapter": "libreoffice_writer", "action": "document.inspect", "payload": {"params": {}}}},
        executed=True, result={"nonempty_paragraph_count": 6, "highlighting": {"highlighted_run_count": 0}}))
    observed = {"visible_selected_text_status": "Selected: 33 words, 165 characters",
        "visible_control_text": [{"visible_text": "Find and Replace", "image_pixel_center": [663, 238]},
            {"visible_text": "Close", "image_pixel_center": [864, 545]}],
        "visible_yellow_toolbar_swatch_image_pixel_center": [675, 104]}
    monkeypatch.setattr(hints, "gemini_gui_observations", lambda _: observed)
    out = io.BytesIO()
    Image.new("RGB", (20, 20)).save(out, format="PNG")
    assert "CLOSE the dialog now" in agent._messages(state, out.getvalue(), tools=[])[0]["content"]
    observed["visible_control_text"] = []
    assert "CLICK the observed yellow toolbar swatch" in agent._messages(state, out.getvalue(), tools=[])[0]["content"]
    state.events.append(ExecutionEvent(4, "", {"kind": "gui", "arguments": {
        "action": "click", "x": 675, "y": 104}}, executed=True))
    assert "Call document.inspect now" in agent._messages(state, out.getvalue(), tools=[])[0]["content"]


def test_gemini_native_paragraph_arrays_and_wrapped_highlight_readback():
    from integrations.lite_agent.task_stage_hints import _cross_app_hint
    state = RuntimeState("synthetic", "multi_apps", "Copy all Gemini values and highlight Iliad.")
    def event(step, adapter, action, params=None, body=None):
        return ExecutionEvent(step, "", {"action": "adapter.call", "arguments": {
            "adapter": adapter, "action": action, "payload": {"params": params or {}}}}, executed=True,
            result={"adapter_response": {"result": {"response": {"result": body or {}}}}})
    state.events = [event(0, "os", "command.run", {"argv": ["python3", "-c",
        "walk=lambda x:x; gemini=[]; open('/tmp/gemini-responses.txt','w')"],
        "cwd_source": "home", "provenance": "shell_history"}, {"returncode": 0}),
        event(1, "libreoffice_writer", "document.create")]
    text = "Keep the whole first response.\n\nIliad in the second response."
    state.events.append(event(2, "vs_code", "file.read_text", {"path": "/tmp/gemini-responses.txt"},
        {"files": [{"source_total_chars": len(text), "chunks": [{"start_char": 0, "text": text}]}]}))
    hint = _cross_app_hint(state, "gemini-document")
    call = json.loads(hint[hint.index('{"adapter"'):])
    assert call["action"] == "document.append_paragraphs"
    assert call["payload"]["params"] == {"paragraphs": text.split("\n\n"), "blank_paragraphs_between": 1}
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False,
        task_stage_hints=PROFILE, task_stage_hint_targets={"synthetic": "gemini-document"}),
        object(), model_client=SimpleNamespace(client=object()))
    out = io.BytesIO()
    Image.new("RGB", (20, 20)).save(out, format="PNG")
    missing_api = agent._messages(state, out.getvalue(), tools=[])
    assert "call tools_search now" in missing_api[0]["content"]
    assert text.split("\n\n")[0] not in json.dumps(missing_api)
    tool = {"type": "function", "function": {"name": "adapter__adapter_call", "parameters": {
        "type": "object", "properties": {"action": {"type": "string", "enum": ["document.append_paragraphs"]}}}}}
    ready = agent._messages(state, out.getvalue(), tools=[tool])
    assert "CALL libreoffice_writer document.append_paragraphs" in ready[0]["content"]
    assert json.loads(ready[-1]["content"][0]["text"])["next_public_call"] == call
    state.events += [event(3, "libreoffice_writer", "document.append_paragraphs", call["payload"]["params"]),
        event(4, "libreoffice_writer", "document.inspect", body={"nonempty_paragraph_count": 2,
            "highlighting": {"highlighted_run_count": 1}})]
    assert _cross_app_hint(state, "gemini-document").startswith("PERSIST:")
    assert "libreoffice_writer document.save" in agent._messages(state, out.getvalue(), tools=[])[0]["content"]
    tool["function"]["parameters"]["properties"]["action"]["enum"] = ["document.save"]
    saving = agent._messages(state, out.getvalue(), tools=[tool])
    assert json.loads(saving[-1]["content"][0]["text"])["next_public_call"]["action"] == "document.save"
    state.events += [event(5, "libreoffice_writer", "document.save"),
        event(6, "libreoffice_writer", "document.inspect", body={"nonempty_paragraph_count": 2,
            "highlighting": {"highlighted_run_count": 1}})]
    assert "call propose_done now" in agent._messages(state, out.getvalue(), tools=[])[0]["content"]


def test_vlc_gui_playback_and_persisted_preference_use_actual_readback():
    from integrations.lite_agent.task_stage_hints import _vlc_hint
    state = RuntimeState("synthetic", "vlc", "Play the Desktop music video.")
    state.events = [ExecutionEvent(1, "", {"kind": "gui", "arguments": {"action": "press", "key": "enter"}}, executed=True),
        ExecutionEvent(2, "", {"action": "playback.status", "arguments": {}}, executed=True,
            result={"state": "playing", "source": "/home/user/Desktop/observed-video.mp4"})]
    assert _vlc_hint(state, "vlc-play").startswith("FINISH:")
    state.events = [ExecutionEvent(1, "", {"action": "preferences.configure", "arguments": {
        "allow_multiple_instances": False}}, executed=True,
        result={"semantic_preferences": {"allow_multiple_instances": False}})]
    assert _vlc_hint(state, "vlc-instances").startswith("SET PREFERENCE:")
    state.events.append(ExecutionEvent(2, "", {"action": "preferences.configure", "arguments": {
        "allow_multiple_instances": True}}, executed=True,
        result={"semantic_preferences": {"allow_multiple_instances": True}}))
    assert _vlc_hint(state, "vlc-instances").startswith("FINISH:")
