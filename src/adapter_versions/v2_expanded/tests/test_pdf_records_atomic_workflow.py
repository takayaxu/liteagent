from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import jsonschema
import pytest

from calc_adapter import uno_worker
from calc_adapter.errors import AdapterError
from calc_adapter.schema import validate_action_params
from integrations.lite_agent import batch_table_semantics, pdf_table_selection as selection
from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.tool_catalog import search_actions


def event(step, action, params, result):
    return ExecutionEvent(step, "2026-10-11T00:00:00Z", {
        "kind": "adapter", "action": "adapter.call",
        "arguments": {"adapter": "os" if action.startswith(("pdf.", "filesystem.")) else "libreoffice_calc", "action": action, "payload": {"params": params}},
    }, executed=True, result=result)


def sample():
    state = RuntimeState("synthetic", "multi_apps", "Read each PDF report table, select the Robotics row and university columns, organize the results in a new table and save as /tmp/results.xlsx.")
    paths = ["/tmp/report31.pdf", "/tmp/report32.pdf"]
    state.events.append(event(1, "filesystem.find", {}, {"matches": [{"path": path, "kind": "file"} for path in paths]}))
    for step, path in enumerate(paths, 2):
        state.events.append(event(step, "pdf.tables.inspect", {"input_path": path}, {
            "input_path": path, "table_count": 1, "row_offset": 0, "column_count": 3,
            "rows": [["Subject", "University Z", None], [None, "Submitted", "Accepted"], ["Robotics", "8", "3"]],
            "merged_cells": [{"row": 0, "column": 1, "row_span": 1, "column_span": 2}],
            "aligned_rows": [{"row_index": 2, "subrow_index": 0, "values": ["Robotics", "8", "3"]}],
        }))
    args = {
        "key_header": "Period", "row_label": "Robotics",
        "sources": [{"observation_step": step, "input_path": path, "row_index": 2, "subrow_index": 0, "key": key, "key_evidence": str(key)[-2:]} for step, path, key in zip([2, 3], paths, [2031, 2032])],
        "fields": [{"name": "Sent", "header_path": "University Z / Submitted"}, {"name": "Approved", "header_path": "University Z / Accepted"}],
        "ratio": {"name": "Ratio", "numerator": "Approved", "denominator": "Sent"},
    }
    return state, args


def test_model_selected_computation_write_rejection_and_repair():
    state, args = sample()
    assert selection.active(state)
    assert batch_table_semantics.native_pdf_table_observation_complete(state)
    jsonschema.validate(args, selection.tool(state)["function"]["parameters"])
    original = deepcopy(args)
    result = selection.compute(state, args)
    assert args == original
    assert result["values"] == [[2031, 8, 3, 0.375], [2032, 8, 3, 0.375]]
    state.events.append(ExecutionEvent(4, "", {"kind": "computation", "action": selection.ACTION}, executed=True, result=result))
    params = {"sheet": "Data", "range": "A1:D3", "values": [result["headers"], *result["values"]]}
    assert not selection.write_errors(state, params)
    bad = deepcopy(params)
    bad["values"][1][1] = 100
    assert "source evidence mismatch" in selection.write_errors(state, bad)[0]
    assert not selection.write_errors(state, params)
    omitted = deepcopy(args)
    omitted["sources"].pop()
    with pytest.raises(ValueError, match="exactly one"):
        selection.compute(state, omitted)
    wrong = deepcopy(args)
    wrong["row_label"] = "Other discipline"
    with pytest.raises(ValueError, match="row_label"):
        selection.compute(state, wrong)


def test_new_workbook_is_unsaved_and_preserves_previous_on_failure():
    validate_action_params("workbook.create_new", {})
    with pytest.raises(AdapterError, match="range.write"):
        validate_action_params("workbook.create_new", {"headers": ["Period"], "rows": [[2031]], "output_path": "/tmp/output.xlsx"})
    previous = object()
    sheet = SimpleNamespace(getName=lambda: "Data")
    doc = SimpleNamespace(supportsService=lambda _: True, getSheets=lambda: SimpleNamespace(getByIndex=lambda _: sheet, getElementNames=lambda: ("Data",)))
    session = SimpleNamespace(doc=previous, desktop=SimpleNamespace(loadComponentFromURL=lambda *_: doc))
    result = uno_worker._create_new(session, {})
    assert result["saved"] is False and result["written_cells"] == 0
    assert session.doc is doc
    session.doc = previous
    session.desktop.loadComponentFromURL = lambda *_: None
    with pytest.raises(AdapterError):
        uno_worker._create_new(session, {})
    assert session.doc is previous


def test_filename_evidence_and_first_column_conflict_have_minimal_repairs():
    state, args = sample()
    bad = deepcopy(args)
    bad["sources"][0]["key_evidence"] = "Robotics"
    original = deepcopy(bad)
    with pytest.raises(ValueError, match=r"sources\[0\].key_evidence.*filename='report31.pdf'.*Keep key=2031"):
        selection.compute(state, bad)
    assert bad == original
    bad["sources"][0]["key_evidence"] = "31"
    assert selection.compute(state, bad)["values"][0][0] == 2031

    duplicate = deepcopy(args)
    duplicate["fields"].insert(0, {"name": "Period", "header_path": "Subject"})
    with pytest.raises(ValueError, match=r"fields\[0\].name duplicates key_header.*Remove only"):
        selection.compute(state, duplicate)
    state.events.append(ExecutionEvent(4, "", {"action": selection.ACTION, "arguments": duplicate}))
    schema = selection.tool(state)["function"]["parameters"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(duplicate, schema)
    jsonschema.validate(args, schema)
    # The same relation is expressible on the first turn for instruction-
    # supplied quoted headers, without baking any particular header into code.
    state.events.pop()
    state.instruction += ' Use headers "Period", "Sent", "Approved", "Ratio".'
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(duplicate, selection.tool(state)["function"]["parameters"])


def test_schema_does_not_lease_undiscovered_calc_route():
    state, args = sample()
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused/v1", include_gui=False), SimpleNamespace())
    names = [tool["function"]["name"] for tool in agent.tools(state)]
    assert selection.TOOL_NAME in names and "adapter__adapter_call" not in names
    assert "repair_confirm" not in names
    result = selection.compute(state, args)
    state.events.append(ExecutionEvent(4, "", {"kind": "computation", "action": selection.ACTION}, executed=True, result=result))
    assert selection.allowed_routes(state) == {("libreoffice_calc", "workbook.create_new")}
    assert "adapter__adapter_call" not in [tool["function"]["name"] for tool in agent.tools(state)]
    matches = search_actions("multi_apps", "libreoffice_calc.workbook.create_new", strict_generic=True)
    state.events.append(ExecutionEvent(5, "", {"kind": "catalog", "action": "tools_search"}, executed=True, result={"matches": matches}))
    tools = agent.tools(state)
    call = next(tool for tool in tools if tool["function"]["name"] == "adapter__adapter_call")
    jsonschema.validate({"adapter": "libreoffice_calc", "action": "workbook.create_new", "payload": {"params": {}}}, call["function"]["parameters"])
    assert "rows" not in json.dumps(call["function"]["parameters"])


def test_exact_output_headers_and_explicit_percentage_display_sequence():
    state, args = sample()
    state.instruction += ' Use headers "Period", "#Sent", "#Approved", "Ratio" (in percentage form with 2 decimal places).'
    with pytest.raises(ValueError, match="exact order and spelling"):
        selection.compute(state, args)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(args, selection.tool(state)["function"]["parameters"])
    args["fields"][0]["name"] = "#Sent"
    args["fields"][1]["name"] = "#Approved"
    args["ratio"].update(numerator="#Approved", denominator="#Sent")
    jsonschema.validate(args, selection.tool(state)["function"]["parameters"])
    result = selection.compute(state, args)
    contract = result["display_contract"]
    assert contract["instruction_evidence"] == ["percentage form", "2 decimal places"]
    assert contract["expected_display"] == ["37.50%", "37.50%"]
    assert contract["numeric_values"] == [0.375, 0.375]
    state.events.append(ExecutionEvent(4, "", {"action": selection.ACTION}, executed=True, result=result))
    state.events.append(event(5, "workbook.create_new", {"sheet_name": "Output"}, {"status": "ok"}))
    params = {"sheet": "Output", "range": "C4:F6", "values": [result["headers"], *result["values"]]}
    wrong_display = deepcopy(params)
    wrong_display["values"][1][-1] = "37.50%"
    rejection = selection.write_errors(state, wrong_display)[0]
    assert "According to the user instruction" in rejection
    assert "correct display text" in rejection
    assert "number_format='0.00%'" in rejection
    assert not selection.write_errors(state, params)
    state.events.append(event(6, "range.write", params, {"status": "ok"}))
    assert selection.allowed_routes(state) == {("libreoffice_calc", "range.format")}
    target = {"sheet": "Output", "range": "F5:F6", "format": {"number_format": "0.00%"}}
    assert selection.percentage_format_target(state) == target
    assert "F5:F6" in selection.stage_hint(state)
    assert "already been written successfully" in selection.stage_hint(state)
    assert state.workflow_progress()["pending_phase"] == "range.format"
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused/v1", include_gui=False), SimpleNamespace())
    assert "adapter__adapter_call" not in [tool["function"]["name"] for tool in agent.tools(state)]
    search = next(tool for tool in agent.tools(state) if tool["function"]["name"] == "tools_search")
    query_schema = search["function"]["parameters"]
    jsonschema.validate({"query": "libreoffice_calc.range.format"}, query_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"query": "libreoffice_calc.workbook.save_as"}, query_schema)
    found = agent.execute_proposal(state, {
        "tool": "tools_search", "arguments_raw": json.dumps({"query": "libreoffice_calc.range.format"}),
        "_model_visible_tools": agent.tools(state),
    })
    assert found.executed, found.error
    assert [(match["adapter"], match["downstream_action"]) for match in found.result["matches"]] == [("libreoffice_calc", "range.format")]
    assert any(tool["function"]["name"] == "adapter__adapter_call" for tool in agent.tools(state))
    for wrong in ({**target, "range": "E5:E6"}, {**target, "sheet": "Other"}, {**target, "format": {"number_format": "0%"}}):
        assert selection.format_errors(state, wrong)
    state.events.append(event(7, "range.format", {**target, "range": "E5:E6"}, {"status": "ok"}))
    assert selection.allowed_routes(state) == {("libreoffice_calc", "range.format")}
    state.events.append(event(8, "range.format", target, {"status": "ok"}))
    assert selection.allowed_routes(state) == {("libreoffice_calc", "workbook.save_as")}
    state.events.append(event(9, "workbook.save_as", {"output_path": "/tmp/results.xlsx"}, {"status": "ok"}))
    assert selection.allowed_routes(state) == {("libreoffice_calc", "range.read")}
    assert "C4:F6" in selection.stage_hint(state)
    display = [[str(value) for value in row] for row in params["values"]]
    for row in display[1:]:
        row[-1] = "37.50%"
    state.events.append(event(10, "range.read", {"sheet": "Output", "range": "C4:F6"}, {"values": params["values"], "display_text": display}))
    assert selection.complete(state)
    display[1][-1] = "37.5%"
    assert not selection.complete(state)
    assert result["values"][0][-1] == 0.375


def test_requested_column_group_matches_whole_header_not_substring():
    state, args = sample()
    state.instruction += " Extract University Z's results."
    columns = ["University Z / Submitted", "Other University Z / Submitted"]
    assert selection.requested_column_group(state, columns) == "University Z"
    args["fields"][0]["header_path"] = "Other University Z / Submitted"
    with pytest.raises(ValueError, match="explicitly requested observed column group"):
        selection.compute(state, args)
    state.instruction += " Compare Other University Z."
    assert selection.requested_column_group(state, columns) is None


def test_percentage_contract_uses_requested_decimal_places():
    state, args = sample()
    state.instruction += " Display the ratio in percentage form with 3 decimal places."
    result = selection.compute(state, args)
    assert result["display_contract"]["number_format"] == "0.000%"
    assert result["display_contract"]["expected_display"] == ["37.500%", "37.500%"]
    assert result["display_contract"]["decimal_places_source"] == "instruction"
    assert result["values"][0][-1] == 0.375
