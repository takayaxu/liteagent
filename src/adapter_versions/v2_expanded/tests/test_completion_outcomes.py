"""Focused contracts for native outcome rejection and autonomous correction."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from calc_adapter.uno_worker import _pivot_field_snapshot
from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.completion_outcomes import completion_outcome_issues, outcome_retry_allowed
from integrations.lite_agent.completion_recovery import completion_rejection_error
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


def event(step, action, args=None, result=None):
    return ExecutionEvent(
        step=step, timestamp_utc="2030-01-01T00:00:00Z",
        proposed={"kind": "adapter", "action": action, "arguments": args or {}},
        parsed=True, validated=True, executed=True, result={"context_hint": result or {}},
    )


def pivot(name, group, output):
    return {"name": name, "source_sheet": "Input", "source_range": "C4:E7",
            "row_fields": [group], "column_fields": [], "page_fields": [],
            "data_fields": [{"field": "Amount ($)", "aggregation": "sum", "show_data_as": "none"}],
            "output_range": output}


def inventory(pivots):
    return {"url": "file:///tmp/Report.xlsx", "sheets": [
        {"name": "Input", "pivot_tables": [], "charts": []},
        {"name": "Summary", "pivot_tables": pivots, "charts": []},
    ]}


def state():
    pivots = [pivot("ByRegion", "Region", "H3:I6"), pivot("ByDepartment", "Department", "H9:I12")]
    source = [["Region", "Department", "Amount ($)"], ["East", "A", "10"],
              ["West", "B", "20"], ["East", "B", "5"]]
    events = [event(1, "workbook.inspect", result={"sheets": [{"name": "Input", "pivot_tables": [], "charts": []}]}),
              event(2, "range.read", {"sheet": "Input", "range": "C4:E7"}, {"display_text": source}),
              event(3, "sheet.create", {"name": "Summary"})]
    for i, p in enumerate(pivots, 4):
        args = {k: v for k, v in p.items() if k != "output_range"}
        args.update(destination_sheet="Summary", destination=p["output_range"].split(":")[0])
        events.append(event(i, "pivot.create", args, {"output_range": p["output_range"]}))
    events += [event(6, "workbook.save"), event(7, "workbook.inspect", result=inventory(pivots)),
               event(8, "range.read", {"sheet": "Summary", "range": "H3:I6"},
                     {"display_text": [["Region", "Sum - Amount ($)"], ["East", "15"], ["West", "20"], ["Total Result", "35"]]}),
               event(9, "range.read", {"sheet": "Summary", "range": "H9:I12"},
                     {"display_text": [["Department", "Sum - Amount ($)"], ["A", "10"], ["B", "25"], ["Total Result", "35"]]})]
    return RuntimeState(task_id="synthetic-outcomes", domain="libreoffice_calc",
                        instruction='Create two pivot tables in a new sheet named "Summary" showing the total amount for each region and department.',
                        events=events)


def agent(executor=None):
    class NoExecution:
        def execute(self, *args):
            raise AssertionError("Inspection/tool selection must not execute repairs")
    return LiteAgent(LiteAgentConfig(base_url="http://unused/v1", include_gui=False),
                     executor or NoExecution(), model_client=SimpleNamespace(client=object()))


def codes(current):
    return {issue["code"] for issue in completion_outcome_issues(current)}


def test_actual_definitions_and_values_allow_completion():
    current = state()
    assert completion_outcome_issues(current) == []
    assert agent()._generic_completion_gate(current)["passed"]


@pytest.mark.parametrize("defect", ["cross_tab", "aggregation", "source_range", "source_sheet", "percent"])
def test_successful_calls_do_not_override_wrong_native_definition(defect):
    current = state()
    p = current.events[6].result["context_hint"]["sheets"][1]["pivot_tables"][0]
    if defect == "cross_tab":
        p["column_fields"] = ["Department"]
    elif defect == "aggregation":
        p["data_fields"][0]["aggregation"] = "count"
    elif defect == "percent":
        p["data_fields"][0]["show_data_as"] = "row_percentage"
    else:
        p[defect] = "A1:C3" if defect == "source_range" else "Other"
    gate = agent()._generic_completion_gate(current)
    assert not gate["passed"]
    assert "pivot.definition_mismatch" in codes(current)
    assert gate["outcome_issues"][0]["target"]["name"] == "ByRegion"
    assert current.completion_rejections == 0
    tools = agent().tools(current)
    names = {t["function"]["name"] for t in tools}
    assert {"adapter__pivot_create", "adapter__range_read", "adapter__workbook_inspect", "adapter__workbook_save", "tools_search"} <= names
    assert "completion_revise" not in names
    error = completion_rejection_error(gate, gate)
    assert error["outcome_issues"] == gate["outcome_issues"]


@pytest.mark.parametrize("defect,code", [
    ("missing_category", "pivot.output_mismatch"), ("wrong_value", "pivot.output_mismatch"),
    ("duplicate_category", "pivot.output_mismatch"), ("truncated", "pivot.output_unverified"),
    ("unrelated_read", "pivot.output_unverified"), ("wrong_sheet", "pivot.output_unverified"),
    ("stale", "workbook.final_inventory_unverified"), ("overlap", "pivot.outputs_overlap"),
    ("missing_definition", "pivot.definition_unverified"), ("duplicate_name", "pivot_tables.missing_objects"),
    ("inventory_error", "pivot_tables.inventory_incomplete"),
])
def test_missing_and_wrong_outcomes_remain_blocked(defect, code):
    current = state()
    payload = current.events[7].result["context_hint"]
    pivots = current.events[6].result["context_hint"]["sheets"][1]["pivot_tables"]
    if defect == "missing_category":
        payload["display_text"][1][0] = "Unknown"
    elif defect == "wrong_value":
        payload["display_text"][1][1] = "99"
    elif defect == "duplicate_category":
        payload["display_text"][2][0] = "East"
    elif defect == "truncated":
        payload["truncated"] = True
    elif defect == "unrelated_read":
        current.events[7].proposed["arguments"]["sheet"] = "Input"
    elif defect == "wrong_sheet":
        payload["sheet"] = "Other"
    elif defect == "stale":
        current.events.append(event(10, "range.write", {"sheet": "Summary", "range": "I4", "values": [[99]]}))
    elif defect == "overlap":
        pivots[1]["output_range"] = "H5:I8"
    elif defect == "missing_definition":
        del pivots[0]["row_fields"]
    elif defect == "duplicate_name":
        pivots.pop()
        # Two successes replacing one object cannot satisfy two requested objects.
        current.events[4].proposed["arguments"]["name"] = "ByRegion"
    elif defect == "inventory_error":
        current.events[6].result["context_hint"]["sheets"][1]["pivot_tables_inspect_error"] = "unavailable"
    assert code in codes(current)
    assert not agent()._generic_completion_gate(current)["passed"]


def test_repair_does_not_close_surface_until_saved_and_verified():
    current = state()
    current.events[7].result["context_hint"]["display_text"][1][1] = "99"
    args = deepcopy(current.events[3].proposed["arguments"])
    args["replace"] = True
    current.events.append(event(10, "pivot.create", args))
    assert "adapter__pivot_create" in {t["function"]["name"] for t in agent().tools(current)}
    assert "workbook.final_inventory_unverified" in codes(current)
    current.events += [event(11, "workbook.save"), event(12, "workbook.inspect", result=deepcopy(current.events[6].result["context_hint"]))]
    assert "pivot.output_unverified" in codes(current)
    current.events += [event(13, "range.read", {"sheet": "Summary", "range": "H3:I6"},
                             deepcopy(state().events[7].result["context_hint"])),
                       event(14, "range.read", {"sheet": "Summary", "range": "H9:I12"},
                             deepcopy(state().events[8].result["context_hint"]))]
    assert completion_outcome_issues(current) == []
    assert agent()._generic_completion_gate(current)["passed"]


def test_native_contradiction_allows_identical_model_repair_once():
    current = state()
    # The duplicated call is the LAST content mutation: an unrelated later
    # mutation must not be what permits this retry.
    args = deepcopy(current.events[4].proposed["arguments"])
    args["replace"] = True
    current.events[4].proposed["arguments"] = deepcopy(args)
    current.events[6].result["context_hint"]["sheets"][1]["pivot_tables"][1]["column_fields"] = ["Region"]
    assert outcome_retry_allowed(current, current.domain, "pivot.create", args, 5)
    calls = []

    class Executor:
        def execute(self, domain, action, arguments, metadata):
            calls.append((action, deepcopy(arguments)))
            return {"executed": True, "result": {"name": "ByDepartment"}}

    worker = agent(Executor())
    tools = worker.tools(current)
    result = worker.execute_proposal(current, {"tool": "adapter__pivot_create", "arguments_raw": json.dumps(args), "_model_visible_tools": tools})
    assert result.executed, result.error
    assert calls == [("pivot.create", args)]
    assert result.proposed["arguments"] == args
    assert not outcome_retry_allowed(current, current.domain, "pivot.create", args, result.step)


def test_issue_ledger_survives_protocol_compaction():
    current = state()
    current.events[7].result["context_hint"]["display_text"][1][1] = "99"
    messages = agent()._messages(current, b"", tools=agent().tools(current), protocol_recovery=True)
    text = json.dumps(messages)
    assert "completion_outcomes" in text
    assert "pivot.output_mismatch" in text
    assert 'ByRegion' in text and 'wrong_sums' in text


@pytest.mark.parametrize("reference", [None, SimpleNamespace(ReferenceType=0),
                                        SimpleNamespace(ReferenceType=SimpleNamespace(value="NONE"))])
def test_native_fields_use_indexed_collection_even_if_names_are_empty(reference):
    fields = [SimpleNamespace(Name="Region", Orientation=SimpleNamespace(value="ROW")),
              SimpleNamespace(Name="Amount", Orientation=SimpleNamespace(value="DATA"),
                              Function=SimpleNamespace(value="SUM"), Reference=reference)]
    snapshot = _pivot_field_snapshot(SimpleNamespace(getDataPilotFields=lambda: SimpleNamespace(
        getCount=lambda: len(fields), getByIndex=lambda i: fields[i], getElementNames=lambda: ("", ""))))
    assert snapshot == {"row_fields": ["Region"], "column_fields": [], "page_fields": [],
                        "data_fields": [{"field": "Amount", "aggregation": "sum", "show_data_as": "none"}]}


def test_other_pivot_semantics_are_not_forced_into_independent_sums():
    current = state()
    current.instruction = 'Create two percentage pivot tables in a new sheet named "Summary".'
    assert not any(i["code"].startswith("pivot.") for i in completion_outcome_issues(current))


def test_new_workbook_invalidates_prior_success_evidence():
    current = state()
    current.events.append(event(10, "workbook.create_new"))
    assert "workbook.final_inventory_unverified" in codes(current)


def test_full_native_payload_takes_precedence_over_truncated_context():
    current = state()
    native = deepcopy(current.events[6].result["context_hint"])
    current.events[6].result = {"context_hint": {"sheets": [], "context_truncated": True},
                                "adapter_response": {"result": native}}
    assert completion_outcome_issues(current) == []


def test_completion_audit_and_catalog_search_do_not_invalidate_file_evidence():
    current = state()
    for step, kind in [(10, "search"), (11, "completion"), (12, "model_audit")]:
        extra = event(step, "")
        extra.proposed["kind"] = kind
        current.events.append(extra)
    assert completion_outcome_issues(current) == []


def test_read_from_another_workbook_does_not_verify_output():
    current = state()
    current.events[7].result["context_hint"]["workbook_url"] = "file:///tmp/Other.xlsx"
    assert "pivot.output_unverified" in codes(current)


def test_compacted_raw_envelope_does_not_mask_complete_cell_hint():
    current = state()
    for index in (1, 7, 8):
        current.events[index].result["adapter_response"] = {
            "truncated": True, "result": {"sheet": "Input", "display_summary": {"rows": 4}}}
    assert completion_outcome_issues(current) == []


def test_dispatched_failed_replacement_invalidates_old_good_inventory():
    current = state()
    failed = event(10, "pivot.create", {"name": "ByRegion", "replace": True, "destination_sheet": "Summary"})
    failed.executed = False
    failed.error = {"detail": "old pivot removed, new descriptor rejected"}
    current.events.append(failed)
    assert "workbook.final_inventory_unverified" in codes(current)
    # A validation rejection was never dispatched and cannot change the file.
    failed.validated = False
    assert completion_outcome_issues(current) == []


def test_outcome_recovery_keeps_public_tools_discovered_for_further_repairs():
    current = state()
    current.events[7].result["context_hint"]["display_text"][1][1] = "99"
    search = event(10, "", {"query": "range.format"})
    search.proposed["kind"] = "catalog"
    search.result = {"matches": [{"action": "range.format"}, {"action": "task.execute"}]}
    current.events.append(search)
    names = {t["function"]["name"] for t in agent().tools(current)}
    assert "adapter__range_format" in names
    assert "adapter__task_execute" not in names


@pytest.mark.parametrize("last_row", [4, 6])
def test_header_or_partial_data_read_cannot_redefine_the_complete_source(last_row):
    current = state()
    source_read = current.events[1]
    source_read.proposed["arguments"]["range"] = f"C4:E{last_row}"
    source_read.result["context_hint"]["display_text"] = source_read.result["context_hint"]["display_text"][:last_row - 3]
    issues = completion_outcome_issues(current)
    assert "pivot.source_unverified" in {i["code"] for i in issues}
    assert "pivot.definition_mismatch" not in {i["code"] for i in issues}
    assert issues[0]["target"]["observed_sources"][0] == {"sheet": "Input", "range": "C4:E7"}


def test_native_used_extent_prevents_a_partial_pivot_source_from_certifying_itself():
    current = state()
    for e in current.events:
        if e.proposed.get("action") == "workbook.inspect":
            e.result["context_hint"]["sheets"][0]["used_range_a1"] = "C4:E8"
    assert "pivot.source_unverified" in codes(current)
