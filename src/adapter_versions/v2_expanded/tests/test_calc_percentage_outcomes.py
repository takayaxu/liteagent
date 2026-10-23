"""Saved native percentage contents, independent of tool counts and claims."""
from copy import deepcopy
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from calc_adapter.uno_worker import _pivot_field_snapshot
from integrations.lite_agent.calc_percentage_outcomes import constrain_tool, request
from integrations.lite_agent.completion_outcomes import completion_outcome_issues, outcome_retry_allowed
from integrations.lite_agent.state_model import RuntimeState
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools
from test_completion_outcomes import agent, claim, event


def state():
    source = [["Ticket", "Zone", "Status"], [1, "East", "Open"],
              [2, "West", "Closed"], [3, "East", "Open"], [4, "East", "Closed"]]
    pivots = [{"name": name, "source_sheet": "Input", "source_range": "C4:E8",
               "row_fields": [group], "column_fields": [], "page_fields": [],
               "data_fields": [{"field": group, "aggregation": "count", "show_data_as": "7"}],
               "output_range": area}
              for name, group, area in [("ByZone", "Zone", "H3:I6"), ("ByStatus", "Status", "H8:I11")]]
    snapshot = {"url": "file:///tmp/Report.xlsx", "sheets": [
        {"name": "Input", "used_range_a1": "C4:E8", "pivot_tables": [], "charts": []},
        {"name": "Summary", "pivot_tables": pivots, "charts": []}]}
    rows = [["Zone", "Count - Zone"], ["East", "75.00%"], ["West", "25.00%"], ["Total Result", "100.00%"],
            ["", ""], ["Status", "Count - Status"], ["Closed", "50.00%"], ["Open", "50.00%"], ["Total Result", "100.00%"]]
    native = [["Zone", "Count - Zone"], ["East", .75], ["West", .25], ["Total Result", 1],
              [None, None], ["Status", "Count - Status"], ["Closed", .5], ["Open", .5], ["Total Result", 1]]
    current = RuntimeState(task_id="synthetic-percent", domain="libreoffice_calc", instruction=(
        'Create two pivot tables to show the percentage of Zone and Status. '
        'Put them in a new sheet named "Summary", stacked with a blank line between them.'), events=[
            event(1, "workbook.inspect", result={"sheets": [snapshot["sheets"][0]]}),
            event(2, "range.read", {"sheet": "Input", "range": "C4:E8"}, {
                "display_text": [[str(c) for c in row] for row in source], "values": source,
                "kinds": [["string"] * 3] + [["number", "string", "string"]] * 4}),
            event(3, "sheet.create", {"name": "Summary"}),
            event(4, "pivot.create", {"name": "ByZone", "destination_sheet": "Summary"}),
            event(5, "pivot.create", {"name": "ByStatus", "destination_sheet": "Summary"}),
            event(6, "workbook.save"), event(7, "workbook.inspect", result=snapshot),
            event(8, "range.read", {"sheet": "Summary", "range": "H3:I11"}, {
                "display_text": rows, "values": native,
                "kinds": [["blank" if c is None else "number" if isinstance(c, (int, float)) else "string"
                           for c in row] for row in native]}),
        ])
    return current


def codes(current):
    return {i["code"] for i in completion_outcome_issues(current)}


def test_valid_percentages_finish_without_repair_or_terminal_audit():
    current = state()
    assert completion_outcome_issues(current) == []
    result = claim(agent(), current)
    assert result.executed, result.error
    assert current.done


@pytest.mark.parametrize("fault,expected", [
    ("wrong_measure", "pivot.definition_mismatch"), ("wrong_aggregation", "pivot.definition_mismatch"),
    ("wrong_mode", "pivot.definition_mismatch"), ("missing_definition", "pivot.definition_unverified"),
    ("header", "pivot.output_mismatch"), ("category_header", "pivot.output_mismatch"),
    ("category_native", "pivot.output_mismatch"),
    ("native_value", "pivot.output_mismatch"), ("display", "pivot.output_mismatch"),
    ("numeric_string", "pivot.output_mismatch"), ("duplicate", "pivot.output_mismatch"),
    ("total", "pivot.output_mismatch"), ("total_label", "pivot.output_mismatch"),
    ("partial", "pivot.output_unverified"), ("truncated", "pivot.output_unverified"),
    ("missing_native", "pivot.output_mismatch"), ("gap", "pivot.gap_mismatch"),
    ("source_partial", "pivot.source_unverified"), ("source_mutation", "pivot.source_unverified"),
    ("read_before_save", "pivot.output_unverified"),
])
def test_live_defects_reject_claim_and_expose_repair(fault, expected):
    current = state()
    final = current.events[-1].result["context_hint"]
    pivot = current.events[6].result["context_hint"]["sheets"][1]["pivot_tables"][0]
    if fault == "wrong_measure":
        pivot["data_fields"][0]["field"] = "Ticket"
    elif fault == "wrong_aggregation":
        pivot["data_fields"][0]["aggregation"] = "sum"
    elif fault == "wrong_mode":
        pivot["data_fields"][0]["show_data_as"] = "row_percentage"
    elif fault == "missing_definition":
        del pivot["data_fields"]
    elif fault == "header":
        final["display_text"][0][1] = "Count - Ticket"
    elif fault == "category_header":
        final["display_text"][0][0] = "zone"
    elif fault == "category_native":
        final["values"][1][0] = "East "
    elif fault == "native_value":
        final["values"][1][1] = .7
    elif fault == "display":
        final["display_text"][1][1] = "0.75"
    elif fault == "numeric_string":
        final["kinds"][1][1] = "string"
    elif fault == "duplicate":
        final["display_text"][2][0] = "East"
    elif fault == "total":
        final["values"][3][1] = 0
    elif fault == "total_label":
        final["display_text"][3][0] = "Other"
    elif fault == "partial":
        current.events[-1].proposed["arguments"]["range"] = "A1:B1"
    elif fault == "truncated":
        final["truncated"] = True
    elif fault == "missing_native":
        del final["values"]
    elif fault == "gap":
        final["display_text"][4][0] = "leftover"
    elif fault == "source_partial":
        current.events[0].result["context_hint"]["sheets"][0]["used_range_a1"] = "C4:E20"
        current.events[6].result["context_hint"]["sheets"][0]["used_range_a1"] = "C4:E20"
    elif fault == "source_mutation":
        current.events[2].proposed["action"] = "range.write"
        current.events[2].proposed["arguments"] = {"sheet": "Input", "range": "D5"}
    elif fault == "read_before_save":
        current.events[-1].step = 5
    assert expected in codes(current)
    worker = agent()
    result = claim(worker, current)
    assert not result.executed and not current.done
    tools = {t["function"]["name"] for t in worker.tools(current)}
    assert {"adapter__pivot_create", "adapter__range_read", "adapter__workbook_save", "tools_search"} <= tools


def test_newer_repair_evidence_clears_defect_and_old_rejection():
    current = state()
    correct = deepcopy(current.events[-1])
    current.events[-1].result["context_hint"]["display_text"][0][1] = "Count - Ticket"
    worker = agent()
    assert not claim(worker, current).executed
    # Re-saving without correction/readback must keep the defect open.
    current.events.extend([event(10, "workbook.save"), deepcopy(current.events[6])])
    current.events[-1].step = 11
    assert "pivot.output_unverified" in codes(current)
    correct.step = 12
    current.events.append(correct)
    assert completion_outcome_issues(current) == []
    assert claim(worker, current).executed


def test_category_schema_binds_measure_and_group_in_normal_and_recovery_tools():
    current = state()
    for tools in [build_tools("libreoffice_calc", ["pivot.create"], include_gui=False), agent().tools(current)]:
        # Normal surface is also called here explicitly; ready state only has controls.
        for tool in tools:
            constrain_tool(tool["function"], current)
            if tool["function"]["name"] != "adapter__pivot_create":
                continue
            schema = tool["function"]["parameters"]
            args = {"source_sheet": "Input", "source_range": "C4:E8", "destination_sheet": "Summary",
                    "destination": "H3", "name": "ByZone", "row_fields": ["Zone"],
                    "data_fields": [{"field": "Zone", "aggregation": "count", "show_data_as": "total_percentage"}]}
            Draft202012Validator(schema).validate(args)
            args["data_fields"][0]["field"] = "Ticket"
            assert list(Draft202012Validator(schema).iter_errors(args))
    current.events[-1].result["context_hint"]["display_text"][0][1] = "Count - Ticket"
    tool = next(t for t in agent().tools(current) if t["function"]["name"] == "adapter__pivot_create")
    assert tool["function"]["parameters"]["oneOf"]


def test_evidence_driven_reapplication_for_wrong_native_definition():
    current = state()
    current.events[6].result["context_hint"]["sheets"][1]["pivot_tables"][0]["data_fields"][0]["field"] = "Ticket"
    args = {"name": "ByZone", "destination_sheet": "Summary", "replace": True,
            "source_sheet": "Input", "source_range": "C4:E8", "row_fields": ["Zone"],
            "data_fields": [{"field": "Zone", "aggregation": "count", "show_data_as": "total_percentage"}]}
    assert outcome_retry_allowed(current, current.domain, "pivot.create", args, 4)
    assert not outcome_retry_allowed(current, current.domain, "pivot.create", args, 7)
    args["data_fields"][0]["field"] = "Ticket"
    assert not outcome_retry_allowed(current, current.domain, "pivot.create", args, 4)


def test_single_discovered_wrapped_pivot_has_same_category_constraint():
    tools = constrain_adapter_call_routes(
        build_tools("multi_apps", ["adapter.call"], include_gui=False, strict_generic=True),
        [("libreoffice_calc", "pivot.create")],
    )
    function = next(t["function"] for t in tools if t["function"]["name"] == "adapter__adapter_call")
    constrain_tool(function, state())
    schema = function["parameters"]
    args = {"adapter": "libreoffice_calc", "action": "pivot.create", "payload": {"params": {
        "source_sheet": "Input", "source_range": "C4:E8", "destination_sheet": "Summary",
        "destination": "H3", "name": "ByZone", "row_fields": ["Zone"],
        "data_fields": [{"field": "Zone", "aggregation": "count", "show_data_as": "total_percentage"}],
    }}}
    Draft202012Validator(schema).validate(args)
    args["payload"]["params"]["data_fields"][0]["field"] = "Ticket"
    assert list(Draft202012Validator(schema).iter_errors(args))


def test_oxford_comma_and_task_independent_names():
    spec = request("Create three pivots showing the percentage of Zone, Account Status, and Age Group.", 3)
    assert spec == {"groups": ["Zone", "Account Status", "Age Group"]}
    assert request("Show two pivot tables with the percentage of sales by Zone and Status.", 2) is None
    assert request("Create two percentage pivot tables.", 2) is None


@pytest.mark.parametrize("mode", ["total_percentage", "column_percentage", "6", "7"])
def test_equivalent_single_column_percentage_definitions(mode):
    current = state()
    current.events[6].result["context_hint"]["sheets"][1]["pivot_tables"][0]["data_fields"][0]["show_data_as"] = mode
    assert completion_outcome_issues(current) == []


@pytest.mark.parametrize("header", ["Zone", "Zone*"])
def test_native_inspection_includes_duplicate_dimension_for_same_field_measure(header):
    # Native getDataPilotFields excludes duplicated dimensions. Orientation
    # collections retain the COUNT measure when the same field also groups.
    row = SimpleNamespace(Name=header, Orientation=SimpleNamespace(value="ROW"))
    measure = SimpleNamespace(Name=header + "*", Orientation=SimpleNamespace(value="DATA"),
                              Function=SimpleNamespace(value="COUNT"), Reference=SimpleNamespace(ReferenceType=7))

    def collection(fields):
        return SimpleNamespace(getCount=lambda: len(fields), getByIndex=lambda i: fields[i])

    pivot = SimpleNamespace(getDataPilotFields=lambda: collection([row]),
                            getRowFields=lambda: collection([row]), getColumnFields=lambda: collection([]),
                            getPageFields=lambda: collection([]), getDataFields=lambda: collection([measure]))
    assert _pivot_field_snapshot(pivot) == {
        "row_fields": [header], "column_fields": [], "page_fields": [],
        "data_fields": [{"field": header, "aggregation": "count", "show_data_as": "7"}],
    }
