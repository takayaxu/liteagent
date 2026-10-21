from __future__ import annotations

import json

from integrations.lite_agent import batch_table_semantics, table_ratio_compute
from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


class _NoAdapter:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("read-only ratio computation must not call an Adapter")


def _event(step: int, action: str, params: dict, result: dict) -> ExecutionEvent:
    return ExecutionEvent(
        step=step,
        timestamp_utc="2026-10-10T00:00:00Z",
        proposed={
            "kind": "adapter", "action": "adapter.call",
            "arguments": {"adapter": "os" if action != "workbook.inspect" else "libreoffice_calc",
                          "action": action, "payload": {"params": params}},
        },
        executed=True,
        result={"adapter_response": {"result": {"response": {"result": result}}}},
    )


def test_ratio_matrix_is_model_selected_read_only_and_write_stays_model_owned() -> None:
    state = RuntimeState(
        task_id="synthetic-ratio",
        domain="multi_apps",
        instruction=(
            "For each year and university, fill the open spreadsheet with the decimal "
            "Supported/Application success rate for Computing Science & Information Technology."
        ),
    )
    paths = ["/tmp/report25.pdf", "/tmp/report26.pdf"]
    state.events.append(_event(1, "filesystem.find", {}, {
        "matches": [{"path": path, "kind": "file"} for path in paths]
    }))
    for index, path in enumerate(paths, start=2):
        rows = [
            ["Subject", "Uni A", None, None, None, "Uni B", None, None, None],
            [None, "Application", None, "Supported", None,
             "Application", None, "Supported", None],
            [None, "No", "Amt", "No", "Amt", "No", "Amt", "No", "Amt"],
            ["Engineering\nCivil Engineering\nComputing Science & Information Technology",
             f"5\n{10 + index}", "0", "1\n6", "0",
             f"2\n{20 + index}", "0", "0\n11", "0"],
        ]
        state.events.append(_event(index, "pdf.tables.inspect", {"input_path": path}, {
            "input_path": path, "table_count": 1, "row_count": 4,
            "column_count": 9, "rows": rows,
        }))
    state.events.append(_event(4, "workbook.inspect", {}, {
        "sheets": [{"name": "Sheet1", "used_range": {
            "start_row": 0, "end_row": 2, "start_column": 0, "end_column": 2,
        }}]
    }))
    state.events.append(_event(5, "range.read", {"sheet": "Sheet1", "range": "A1:C3"}, {
        "sheet": "Sheet1", "range": "A1:C3",
        "display_text": [["Year", "Uni A", "Uni B"], ["2025", "", ""], ["2026", "", ""]],
    }))
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused/v1", include_gui=False),
        _NoAdapter(),  # type: ignore[arg-type]
    )
    assert batch_table_semantics._decimal_rate_matrix_requested(state)
    assert batch_table_semantics._observed_pdf_source_paths(state) == tuple(paths)
    assert batch_table_semantics.native_pdf_table_observation_complete(state)
    assert batch_table_semantics._valid_target_inspection(state) is not None
    assert table_ratio_compute.target_layout(state) is not None
    tools = agent.tools(state)
    assert [item["function"]["name"] for item in tools] == [table_ratio_compute.TOOL_NAME]
    parameters = tools[0]["function"]["parameters"]["properties"]
    assert parameters["sources"]["items"]["properties"]["row_key"]["enum"] == ["2025", "2026"]
    assert parameters["column_keys"]["items"]["enum"] == ["Uni A", "Uni B"]
    arguments = {
        "sources": [
            {"input_path": paths[0], "row_key": "2025"},
            {"input_path": paths[1], "row_key": "2026"},
        ],
        "column_keys": ["Uni A", "Uni B"],
        "source_row_label": "Engineering\nCivil Engineering\nComputing Science & Information Technology",
        "line_index": 1,
        "numerator": "Supported",
        "denominator": "Application",
    }
    event = agent.execute_proposal(state, {
        "tool": table_ratio_compute.TOOL_NAME,
        "arguments_raw": json.dumps(arguments),
        "_model_visible_tools": tools,
    })
    assert event.executed, event.error
    assert event.proposed["kind"] == "computation"
    assert event.result["values"] == [[6 / 12, 11 / 22], [6 / 13, 11 / 23]]
    assert batch_table_semantics._observed_decimal_rate_target(state)["range"] == "B2:C3"
    first = batch_table_semantics._decimal_rate_next_write_target(state)
    assert first["range"] == "B2:C2"
    assert first["values"] == [[6 / 12, 11 / 22]]
    facade_schema = {"name": "adapter__adapter_call", "parameters": {"properties": {
        "payload": {"properties": {"params": {"properties": {
            "sheet": {"type": "string"}, "range": {"type": "string"},
            "values": {"type": "array"},
        }}}},
    }}}
    batch_table_semantics.constrain_tool_schema(facade_schema, state)
    write_properties = facade_schema["parameters"]["properties"]["payload"]["properties"]["params"]["properties"]
    assert write_properties["range"]["enum"] == ["B2:C2"]
    assert "[[0.5, 0.5]]" in write_properties["values"]["description"]
    search = agent.execute_proposal(state, {
        "tool": "tools_search",
        "arguments_raw": json.dumps({"query": "pdf.extract_text_batch"}),
        "_model_visible_tools": agent.tools(state),
    })
    assert search.executed, search.error
    assert [(match["adapter"], match["downstream_action"])
            for match in search.result["matches"]] == [
                ("libreoffice_calc", "range.write")
            ]
    actual_tools = agent.tools(state)
    actual_write = next(tool["function"] for tool in actual_tools
                        if tool["function"]["name"] == "adapter__adapter_call")
    actual_params = actual_write["parameters"]["properties"]["payload"]["properties"]["params"]["properties"]
    assert actual_params["range"]["enum"] == ["B2:C2"]
    assert "[[0.5, 0.5]]" in actual_params["values"]["description"]
    message_text = agent._messages(state, b"png", tools=actual_tools)[-1]["content"][0]["text"]
    assert '"range": "B2:C2"' in message_text
    assert '"computed_values": [[0.5, 0.5]]' in message_text
    assert "pdf.tables.inspect" not in message_text
    assert batch_table_semantics.argument_contract_errors(state, "range.write", {
        "sheet": "Sheet1", "range": "B2:C2", "values": first["values"],
    }) == []
    state.events.append(_event(7, "range.write", {
        "sheet": "Sheet1", "range": "B2:C2", "values": first["values"],
    }, {"sheet": "Sheet1", "range": "B2:C2"}))
    second = batch_table_semantics._decimal_rate_next_write_target(state)
    assert second["range"] == "B3:C3"
    assert batch_table_semantics.next_post_mutation_route(state) == ("libreoffice_calc", "range.write")
    assert batch_table_semantics.argument_contract_errors(state, "range.write", {
        "sheet": "Sheet1", "range": "B3:C3", "values": [[0.5, 0.5]],
    })
    state.events.append(_event(8, "range.write", {
        "sheet": "Sheet1", "range": "B3:C3", "values": second["values"],
    }, {"sheet": "Sheet1", "range": "B3:C3"}))
    assert batch_table_semantics._decimal_rate_next_write_target(state) is None
    assert batch_table_semantics.next_post_mutation_route(state) == ("libreoffice_calc", "range.read")
    wrong = {"sheet": "Sheet1", "range": "B2:C3", "values": [[0.5, 0.5], [0.5, 0.5]]}
    assert batch_table_semantics.argument_contract_errors(state, "range.write", wrong)
    state.events.append(_event(9, "range.read", {"sheet": "Sheet1", "range": "A1:C3"}, {
        "display_text": [["Year", "Uni A", "Uni B"], ["2025", "0.5", "0.5"],
                         ["2026", str(6 / 13), str(11 / 23)]],
    }))
    assert batch_table_semantics.next_post_mutation_route(state) == (
        "libreoffice_calc", "workbook.save"
    )
    save_search = agent.execute_proposal(state, {
        "tool": "tools_search",
        "arguments_raw": json.dumps({"query": "pdf.extract_text_batch"}),
        "_model_visible_tools": agent.tools(state),
    })
    assert save_search.executed, save_search.error
    assert [(match["adapter"], match["downstream_action"])
            for match in save_search.result["matches"]] == [
                ("libreoffice_calc", "workbook.save")
            ]
    assert state.repair_contract is None


def test_explicit_stale_pdf_search_promotes_current_source_route() -> None:
    state = RuntimeState(
        task_id="synthetic-route",
        domain="multi_apps",
        instruction=(
            "For each year and university, fill the open spreadsheet with the decimal "
            "Supported/Application success rate from the PDF reports."
        ),
    )
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused/v1", include_gui=False),
        _NoAdapter(),  # type: ignore[arg-type]
    )
    event = agent.execute_proposal(state, {
        "tool": "tools_search",
        "arguments_raw": json.dumps({"query": "pdf.extract_text_batch"}),
        "_model_visible_tools": agent.tools(state),
    })
    assert event.executed, event.error
    assert {match["downstream_action"] for match in event.result["matches"]} == {
        "filesystem.find"
    }
    names = {item["function"]["name"] for item in agent.tools(state)}
    assert "adapter__adapter_call" in names


def test_overall_ratio_uses_exact_aggregate_row_and_observed_workbook_order() -> None:
    state = RuntimeState(
        task_id="synthetic-total",
        domain="multi_apps",
        instruction=(
            "For each year and university, fill the open spreadsheet with the decimal "
            "overall pass rate, Supported/Application, from the PDF files."
        ),
    )
    path = "/tmp/report26.pdf"
    state.events.append(_event(1, "filesystem.find", {}, {
        "matches": [{"path": path, "kind": "file"}]
    }))
    state.events.append(_event(2, "pdf.tables.inspect", {"input_path": path}, {
        "input_path": path, "table_count": 1, "row_count": 4, "column_count": 9,
        "rows": [
            ["Subject", "Uni A", None, None, None, "NewU", None, None, None],
            [None, "Application", None, "Supported", None,
             "Application", None, "Supported", None],
            [None, "No", "Amt", "No", "Amt", "No", "Amt", "No", "Amt"],
            ["Total", "10", "0", "4", "0", "20", "0", "5", "0"],
        ],
    }))
    state.events.append(_event(3, "workbook.inspect", {}, {
        "sheets": [{"name": "Sheet1", "used_range": {
            "start_row": 0, "end_row": 1, "start_column": 0, "end_column": 2,
        }}]
    }))
    assert table_ratio_compute.target_layout(state) is None
    state.events.append(_event(4, "range.read", {"sheet": "Sheet1", "range": "A1:C2"}, {
        "sheet": "Sheet1", "range": "A1:C2",
        "display_text": [["Year", "Uni A", "OldU (NewU)"], ["2026", "", ""]],
    }))
    arguments = {
        "sources": [{"input_path": path, "row_key": "2026"}],
        "column_keys": ["Uni A", "OldU (NewU)"],
        "source_row_label": "Total", "numerator": "Supported", "denominator": "Application",
    }
    assert table_ratio_compute.compute(state, arguments)["values"] == [[0.4, 0.25]]
