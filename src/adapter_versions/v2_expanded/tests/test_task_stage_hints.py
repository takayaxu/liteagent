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


def test_full_queue_other_173_actual_messages_are_unchanged(monkeypatch):
    import integrations.lite_agent.task_stage_hints as hints
    root = Path(__file__).resolve().parents[4]
    config = json.loads((root / "configs/single-task-deadline-stage-hints.json").read_text())
    targets = config["protocol"]["task_stage_hint_targets"]
    basic = LiteAgentConfig(base_url="http://unused", include_gui=False)
    agent = LiteAgent(basic, object(), model_client=SimpleNamespace(client=object()))
    out = io.BytesIO()
    Image.new("RGB", (20, 20)).save(out, format="PNG")
    def unexpected_ocr(*_):
        raise AssertionError("Single-task OCR must never run for an unrelated task")
    monkeypatch.setattr(hints, "_gemini_document_hint", unexpected_ocr)
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


def test_gemini_source_draft_preserves_values_paragraphs_and_highlights(tmp_path):
    from xml.etree import ElementTree as ET
    from integrations.lite_agent.task_stage_hints import _cross_app_hint
    source = tmp_path / "source.json"
    values = ["No keyword\nretain  & preserve <text>", "Iliad response, another Iliad"]
    source.write_text(json.dumps({"first": {"Gemini": values[0], "GPT3": "omit"},
        "next": [{"gemini": values[1]}]}))
    def event(step, adapter, action, params=None, body=None):
        return ExecutionEvent(step, "", {"action": "adapter.call", "arguments": {
            "adapter": adapter, "action": action, "payload": {"params": params or {}}}}, executed=True,
            result={"adapter_response": {"result": {"response": {"result": body or {}}}}})
    state = RuntimeState("synthetic", "multi_apps", "Copy all Gemini responses and highlight Iliad.")
    state.events = [event(1, "vs_code", "file.read_text", {"path": str(source)})]
    hint = _cross_app_hint(state, "gemini-document")
    call = json.loads(hint[hint.index('{"adapter"'):])
    params = call["payload"]["params"]
    output = tmp_path / "draft.fodt"
    script = params["argv"][2].replace("/tmp/gemini-responses.fodt", str(output))
    exec(compile(script, "observed-json-draft", "exec"), {})
    root = ET.parse(output).getroot()
    ns = {"text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}
    paragraphs = root.findall(".//text:p", ns)
    def native_text(element):
        content = element.text or ""
        for child in element:
            content += (" " if child.tag == "{" + ns["text"] + "}s" else
                "\t" if child.tag == "{" + ns["text"] + "}tab" else native_text(child))
            content += child.tail or ""
        return content
    assert [native_text(p) for p in paragraphs] == [values[0].replace("\n", "\\n"), "", values[1]]
    assert [s.text for s in root.findall(".//text:span", ns)] == ["Iliad", "Iliad"]
    state.events.append(event(2, "os", "command.run", params, {"returncode": 0}))
    assert "--infilter=OpenDocument Text Flat XML" in _cross_app_hint(state, "gemini-document")
    state.events.append(event(3, "os", "command.run", {"argv": ["libreoffice", "--writer",
        "--infilter=OpenDocument Text Flat XML", "/tmp/gemini-responses.fodt"], "terminal": True}))
    state.events.append(event(4, "libreoffice_writer", "document.inspect", body={"paragraph_count": 3,
        "nonempty_paragraph_count": 2, "highlighting": {"highlighted_run_count": 2}}))
    save_hint = _cross_app_hint(state, "gemini-document")
    assert '"filter_name": "Office Open XML Text"' in save_hint
    state.events.append(event(5, "libreoffice_writer", "document.save", {
        "url": "/home/user/Desktop/gemini_results.docx"}))
    assert '"action": "document.inspect"' in _cross_app_hint(state, "gemini-document")
    state.events.append(event(6, "libreoffice_writer", "document.inspect", body={"paragraph_count": 3,
        "nonempty_paragraph_count": 2, "highlighting": {"highlighted_run_count": 2}}))
    assert _cross_app_hint(state, "gemini-document").startswith("NATIVE GEMINI FINISH:")


def test_background_stage_uses_observed_paths_and_requires_post_edit_view():
    from integrations.lite_agent.task_stage_hints import _cross_app_hint
    def event(step, adapter, action, params=None, body=None):
        return ExecutionEvent(step, "", {"action": "adapter.call", "arguments": {
            "adapter": adapter, "action": action, "payload": {"params": params or {}}}}, executed=True,
            result={"context_hint": {"downstream_context": body or {}}})
    state = RuntimeState("synthetic", "multi_apps", "Keep the person on a white background.")
    state.events = [event(1, "os", "filesystem.find", body={"matches": [
        {"path": "/home/user/Desktop/observed.jpg", "kind": "file"},
        {"path": "/home/user/Desktop/observed.docx", "kind": "file"}]})]
    hint = _cross_app_hint(state, "person-background")
    assert '"path": "/home/user/Desktop/observed.docx"' in hint
    state.events += [event(2, "libreoffice_writer", "document.read_file"),
        event(3, "os", "desktop.open_path", {"path": "/home/user/Desktop/observed.jpg"})]
    hint = _cross_app_hint(state, "person-background")
    call = json.loads(hint[hint.index('{"adapter"'):])
    params = call["payload"]["params"]
    compile(params["argv"][2], "observed-person-segmentation", "exec")
    assert "/home/user/Desktop/observed.jpg" in params["argv"][2]
    state.events += [event(4, "os", "command.run", params)]
    assert '"action": "desktop.open_path"' in _cross_app_hint(state, "person-background")
    state.events.append(event(5, "os", "desktop.open_path", {"path": "/home/user/Desktop/pic.jpg"}))
    assert _cross_app_hint(state, "person-background").startswith("BACKGROUND FINISH:")
    state.events.append(event(6, "os", "command.run", params))
    assert _cross_app_hint(state, "person-background").startswith("BACKGROUND STEP:")


def test_invoice_selects_observed_attachment_then_discovers_real_receipts_directory():
    from integrations.lite_agent.task_stage_hints import _cross_app_hint
    state = RuntimeState("synthetic", "multi_apps", "File the AWS invoice and append the tally.")
    def event(step, action, body):
        return ExecutionEvent(step, "", {"action": "adapter.call", "arguments": {
            "adapter": "thunderbird", "action": action, "payload": {"params": {}}}}, executed=True,
            result={"context_hint": {"downstream_context": body}})
    state.events = [event(1, "messages.query", {"messages": []})]
    assert '"action": "messages.query"' in _cross_app_hint(state, "invoice-mail")
    state.events.append(event(2, "messages.query", {"messages": [{"sender_name": "AWS",
        "mailbox_index": 7, "attachment_names": ["observed.pdf"]}]}))
    hint = _cross_app_hint(state, "invoice-mail")
    call = json.loads(hint[hint.index('{"adapter"'):])
    params = call["payload"]["params"]
    assert params == {"folder_name": "Bills", "mailbox_index": 7,
        "attachment_name": "observed.pdf", "output_path": "/tmp/observed.pdf"}
    state.events.append(event(3, "attachments.save", {"output_path": "/tmp/observed.pdf"}))
    hint = _cross_app_hint(state, "invoice-mail")
    call = json.loads(hint[hint.index('{"adapter"'):])
    assert call["action"] == "pdf.extract_text_batch"
    assert call["payload"]["params"]["input_pattern"] == "/tmp/observed.pdf"
    state.events.append(event(4, "pdf.extract_text_batch", {"files": []}))
    hint = _cross_app_hint(state, "invoice-mail")
    call = json.loads(hint[hint.index('{"adapter"'):])
    assert call["action"] == "filesystem.find" and call["payload"]["params"]["kind"] == "any"
    assert "~/my receipts" not in hint


def test_invoice_uses_public_a1_projection_with_raw_native_coordinate_result():
    from integrations.lite_agent.task_stage_hints import _cross_app_hint
    def event(step, action, params=None, body=None):
        return ExecutionEvent(step, "", {"kind": "adapter", "action": "adapter.call", "arguments": {
            "adapter": "os", "action": action, "payload": {"params": params or {}}}}, executed=True,
            result={"context_hint": {"downstream_context": body or {}}})
    state = RuntimeState("synthetic", "multi_apps", "File the AWS invoice and append the tally.")
    state.events = [event(1, "messages.query", body={"messages": [{"sender_name": "AWS"}]}),
        event(2, "attachments.save", body={"output_path": "/tmp/observed.pdf"}),
        event(3, "filesystem.find", {"roots": ["/actual/receipts"], "name_patterns": ["*"]}, body={"matches": [
            {"name": "receipts", "path": "/actual/receipts", "kind": "directory"},
            {"name": "old.pdf", "path": "/actual/receipts/old.pdf", "kind": "file"},
            {"name": "tally.xlsx", "path": "/actual/tally.xlsx", "kind": "file"}]}),
        event(4, "pdf.extract_text_batch"),
        event(5, "desktop.open_path", {"path": "/actual/tally.xlsx"}),
        event(6, "workbook.inspect", body={"sheets": [{"name": "Actual", "used_range_a1": "A1:C6"}]})]
    listing_hint = _cross_app_hint(state, "invoice-mail")
    assert "receipt-name-examples" in listing_hint
    listing_call = json.loads(listing_hint[listing_hint.index('{"adapter"'):])
    compile(listing_call["payload"]["params"]["argv"][2], "receipt-list", "exec")
    state.events.insert(4, event(4, "command.run", {"argv": ["python3", "-c", "receipt-name-examples"]},
        {"stdout": json.dumps({"files": [{"path": "/actual/receipts/old.pdf", "name": "old.pdf", "kind": "file"}]})}))
    state.events[-1].result["adapter_response"] = {"result": {"response": {"result": {
        "sheets": [{"name": "Actual", "used_range": {"end_column": 2, "end_row": 5}}]}}}}
    hint = _cross_app_hint(state, "invoice-mail")
    call = json.loads(hint[hint.index('{"adapter"'):])
    assert call["action"] == "range.read"
    assert call["payload"]["params"] == {"sheet": "Actual", "range": "A1:C6"}
    state.events += [event(7, "range.read"), event(8, "filesystem.rename", {
        "source": "/tmp/observed.pdf", "destination": "/actual/receipts/new.pdf"}),
        event(9, "range.write"), event(10, "workbook.save"), event(11, "range.read")]
    hint = _cross_app_hint(state, "invoice-mail")
    call = json.loads(hint[hint.index('{"adapter"'):])
    assert call["action"] == "command.run"
    assert "/actual/receipts/new.pdf" in call["payload"]["params"]["argv"][2]
    compile(call["payload"]["params"]["argv"][2], "receipt-check", "exec")
    state.events.append(event(12, "command.run", call["payload"]["params"]))
    assert _cross_app_hint(state, "invoice-mail").startswith("INVOICE FINISH:")


def test_invoice_combined_discovery_contains_reader_and_append_route():
    from integrations.lite_agent.tool_catalog import search_actions
    matches = search_actions("multi_apps", "libreoffice_calc range.read range.write",
                             limit=7, strict_generic=True)
    routes = {(m.get("adapter"), m.get("downstream_action")) for m in matches}
    assert {("libreoffice_calc", "range.read"), ("libreoffice_calc", "range.write")} <= routes


def test_grading_stage_projects_current_pairs_and_keeps_existing_write_contract(monkeypatch):
    import integrations.lite_agent.grading_progress as progress
    facts = {"stage": "compare_one_student_and_write", "next_step": "WRITE ONE ROW",
        "raw_answer_pairs": [{"reference_answer": "B", "student_answer": "D", "target_cell": "C3"}],
        "write_contract": {"marker_convention_from_original_example": {"equal_letters": "1", "unequal_letters": "0"}},
        "answer_key_source": [{"text": "long earlier source omitted"}]}
    monkeypatch.setattr(progress, "model_progress", lambda *_args, **_kw: facts)
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False,
        task_stage_hints=PROFILE, task_stage_hint_targets={"test-grading": "grading"}),
        object(), model_client=SimpleNamespace(client=object()))
    state = RuntimeState("test-grading", "multi_apps", "Grade remaining students from their answers into the spreadsheet.")
    output = io.BytesIO()
    Image.new("RGB", (20, 20)).save(output, format="PNG")
    messages = agent._messages(state, output.getvalue(), tools=[])
    context = json.loads(messages[-1]["content"][0]["text"])
    assert context["current_stage"]["raw_answer_pairs"] == facts["raw_answer_pairs"]
    assert context["current_stage"]["write_contract"] == facts["write_contract"]
    assert "answer_key_source" not in context["current_stage"]
    assert "SAME branch order" in messages[0]["content"]
