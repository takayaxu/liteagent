"""Boundary defects, native evidence freshness and legal chart layouts."""
from copy import deepcopy

import pytest

from integrations.lite_agent.calc_chart_outcomes import source_issues, _source_range
from integrations.lite_agent.completion_outcomes import _events, completion_outcome_issues
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


def event(step, action, args=None, payload=None):
    return ExecutionEvent(step=step, timestamp_utc="2031-01-01T00:00:00Z",
                          proposed={"kind": "adapter", "action": action, "arguments": args or {}},
                          parsed=True, validated=True, executed=True,
                          result={"context_hint": payload or {}})


def state(values=None, category="C4:C7", ranges=None):
    values = values or [[None, "", None], ["North", 12, 0], ["South", 15, 2], ["West", 18, 4]]
    ranges = ranges or ["E4:E7"]
    chart = {"name": "Costs", "type": "column", "source_sheet": "Raw Data",
             "category_axes": [{"source_range": category, "labels": [r[0] for r in values]}],
             "data_series": [{"source_ranges": [area]} for area in ranges]}
    initial = {"url": "file:///work.ods", "sheets": [{"name": "Raw Data", "charts": []}]}
    final = deepcopy(initial)
    final["sheets"][0]["charts"] = [chart]
    events = [event(1, "workbook.inspect", payload=initial),
              event(2, "range.read", {"sheet": "Raw Data", "range": "C4:E7"},
                    {"sheet": "Raw Data", "range": "C4:E7", "values": values,
                     "workbook_url": "file:///work.ods"}),
              event(3, "chart.create", {"sheet": "Raw Data", "name": "Costs"}),
              event(4, "workbook.save"), event(5, "workbook.inspect", payload=final)]
    return RuntimeState(task_id="synthetic-chart-boundary", domain="libreoffice_calc",
                        instruction="Create one column chart of regional costs.", events=events)


def check(s):
    chart = s.events[-1].result["context_hint"]["sheets"][0]["charts"][0]
    return source_issues(s, _events(s), [("Raw Data", chart)], s.events[-1].step)


def test_empty_boundary_is_rejected_with_observed_sources():
    issues = completion_outcome_issues(state())
    defect = next(i for i in issues if i["code"] == "charts.blank_source_boundary")
    assert defect["kind"] == "state_mismatch"
    assert defect["observed"]["category_range"] == "C4:C7"
    assert defect["observed"]["series_values"] == [None]
    assert "chart.create" in defect["repair_actions"]


def test_source_range_fix_is_accepted_without_forced_header_flags():
    assert check(state(category="C5:C7", ranges=["E5:E7"])) == []


def test_multiple_series_are_checked_independently():
    s = state(category="C5:C7", ranges=["D5:D7", "E5:E7"])
    assert check(s) == []
    s.events[-1].result["context_hint"]["sheets"][0]["charts"][0]["data_series"][1]["source_ranges"] = ["E4:E7"]
    assert check(s)[0]["code"] == "charts.source_length_mismatch"


def test_shifted_equal_length_sources_are_rejected():
    assert check(state(category="C4:C6", ranges=["E5:E7"]))[0]["code"] == "charts.source_alignment_mismatch"


def test_trailing_empty_boundary_is_observed():
    values = [["East", 1, 0], ["West", 2, 0], ["North", 3, 0], [None, None, None]]
    issue = check(state(values))[0]
    assert issue["code"] == "charts.blank_source_boundary" and issue["observed"]["edge"] == "last"


def test_empty_category_with_real_value_is_unknown_not_a_defect():
    values = [[None, 1, 0], ["West", 2, 0], ["North", 3, 0], ["South", 4, 0]]
    issue = check(state(values))[0]
    assert issue["code"] == "charts.blank_category_unverified" and issue["kind"] == "missing_observation"


def test_explicitly_preserved_blank_categories_and_interior_gaps_are_legal():
    s = state()
    s.instruction += " Keep blank categories."
    assert check(s) == []
    values = [["North", 1, 0], [None, None, None], ["West", 2, 0], ["East", 3, 0]]
    assert check(state(values)) == []


@pytest.mark.parametrize("change", ["truncated", "source_truncated", "wrong_document", "wrong_sheet", "wrong_range", "missing_read", "short_matrix", "gui", "write"])
def test_missing_or_stale_native_source_cannot_establish_boundary(change):
    s = state()
    read = s.events[1].result["context_hint"]
    if change in {"truncated", "source_truncated"}:
        read[change] = True
    elif change == "wrong_document":
        read["workbook_url"] = "file:///other.ods"
    elif change == "wrong_sheet":
        read["sheet"] = "Other"
    elif change == "wrong_range":
        read["range"] = "D4:F7"
    elif change == "missing_read":
        del s.events[1]
    elif change == "short_matrix":
        read["values"].pop()
    else:
        mutation = event(3, "range.write", {"sheet": "Raw Data", "range": "C4"})
        if change == "gui":
            mutation.proposed = {"kind": "gui"}
        s.events.insert(2, mutation)
    issues = check(s)
    assert [i["code"] for i in issues] == ["charts.source_unverified"]
    assert issues[0]["kind"] == "missing_observation"


def test_new_read_after_edit_restores_native_proof():
    s = state(category="C5:C7", ranges=["E5:E7"])
    s.events.insert(2, event(3, "range.write", {"sheet": "Raw Data", "range": "D5"}))
    reread = deepcopy(s.events[1])
    reread.step = 4
    s.events.insert(3, reread)
    assert check(s) == []


def test_horizontal_layout_and_quoted_sheet_names():
    s = state()
    read = s.events[1]
    read.proposed["arguments"]["range"] = "D9:G11"
    read.result["context_hint"].update(range="D9:G11", values=[["", "Q1", "Q2", "Q3"],
                                                            [None, 10, 20, 30], [None, 0, 0, 0]])
    chart = s.events[-1].result["context_hint"]["sheets"][0]["charts"][0]
    chart["category_axes"][0]["source_range"] = "$'Raw Data'.$D$9:$G$9"
    chart["data_series"][0]["source_ranges"] = ["$'Raw Data'.$D$10:$G$10"]
    assert check(s)[0]["code"] == "charts.blank_source_boundary"
    assert _source_range("$'O''Brien'.$A$1:$A$3", "unused")[0] == "O'Brien"


def test_partial_series_evidence_is_unknown():
    s = state()
    s.events[-1].result["context_hint"]["sheets"][0]["charts"][0]["data_series"][0]["source_ranges"] = []
    assert check(s)[0]["code"] == "charts.source_unverified"


def test_unmodified_existing_chart_does_not_gain_new_requirements():
    s = state()
    s.events[0].result["context_hint"]["sheets"][0]["charts"] = deepcopy(s.events[-1].result["context_hint"]["sheets"][0]["charts"])
    del s.events[2]
    s.events.insert(2, event(3, "range.format", {"sheet": "Raw Data", "range": "C5"}))
    assert not any(i["code"].startswith("charts.source") or i["code"] == "charts.blank_source_boundary"
                   for i in completion_outcome_issues(s))


def test_new_overlapping_read_prevents_reuse_of_old_source_rectangle():
    s = state()
    s.events.insert(3, event(4, "range.read", {"sheet": "Raw Data", "range": "C4"}, {"values": [["New"]]}))
    assert check(s)[0]["code"] == "charts.source_unverified"


def test_unknown_failed_replacement_does_not_invalidate_unmodified_cells():
    s = state()
    failed = event(4, "chart.create", {"sheet": "Raw Data", "name": "Costs"})
    failed.error = {"code": "CONFLICT"}
    failed.executed = False
    s.events.insert(3, failed)
    assert check(s)[0]["code"] == "charts.blank_source_boundary"
