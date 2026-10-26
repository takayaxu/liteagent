"""Native outcomes for independent period layouts and equivalent calculations."""
import pytest

from integrations.lite_agent.calc_period_outcomes import outcome_issues, request, _range_cells
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState

INSTRUCTION = ('Sum the revenue in a row named "Revenue" and display each month as bars. '
               'Calculate month-on-month growth percentage for Mar to Apr in a row called "Change" '
               'and show a line chart. Set chart titles as the row headers.')


def event(step, action, args=None, payload=None):
    return ExecutionEvent(step=step, timestamp_utc="2030-01-01T00:00:00Z",
                          proposed={"kind": "adapter", "action": action, "arguments": args or {}},
                          parsed=True, validated=True, executed=True, result={"context_hint": payload or {}})


def read(step, area, values, formulas=None):
    return event(step, "range.read", {"sheet": "Data Set", "range": area},
                 {"sheet": "Data Set", "range": area, "values": values,
                  "kinds": [["number" if isinstance(v, (int, float)) else "text" for v in row] for row in values],
                  "formulas": formulas or [["" for v in row] for row in values]})


def state():
    def chart(title, row, start, kind):
        return {"name": title + " chart", "title": title, "type": kind,
                "data_series": [{"source_ranges": [f"$'Data Set'.${start}${row}:$F${row}"]}],
                "category_axes": [{"labels": ["Feb", "Mar", "Apr"] if start == "D" else ["Mar", "Apr"]}]}
    sheet = {"name": "Data Set", "used_range_a1": "C4:F6", "charts": []}
    initial = [["Agent", "Feb", "Mar", "Apr"], ["A", 10, 15, 20], ["B", 30, 45, 40]]
    events = [event(1, "workbook.inspect", payload={"sheets": [sheet]}), read(2, "C4:F6", initial),
              event(3, "range.write", {"sheet": "Data Set", "range": "C7:F8"}),
              event(4, "chart.create", {"sheet": "Data Set"}), event(5, "workbook.save"),
              read(6, "C7:F8", [["Revenue", 40, 60, 60], ["Change", "", .5, 0]],
                   [["", "=SUM(D5:D6)", "=E5+E6", "=SUM(F5:F6)"],
                    ["", "", "=E7/D7-1", "=(F7-E7)/E7"]]),
              event(7, "workbook.inspect", payload={"sheets": [{**sheet, "charts": [
                  chart("Revenue", 7, "D", "bar"), chart("Change", 8, "E", "line")]}]})]
    return RuntimeState(task_id="synthetic-periods", domain="libreoffice_calc", instruction=INSTRUCTION, events=events)


def test_alternate_layout_and_equivalent_formulas():
    assert outcome_issues(state()) == []


def test_shifted_growth_and_incorrect_chart_native_binding():
    s = state()
    payload = s.events[5].result["context_hint"]
    payload["values"][1] = ["Change", .5, 0, ""]
    charts = s.events[-1].result["context_hint"]["sheets"][0]["charts"]
    charts[0]["data_series"][0]["source_ranges"] = ["$'Data Set'.$E$7:$F$7"]
    charts[0]["category_axes"][0]["labels"] = ["Mar", "Apr"]
    issues = outcome_issues(s)
    wrong = next(i for i in issues if i["code"] == "period.values_mismatch")
    assert {v["cell"] for v in wrong["observed"]} == {"D8", "E8", "F8"}
    assert any(i["code"] == "period.chart_mismatch" and i["kind"] == "state_mismatch" for i in issues)


@pytest.mark.parametrize("change", ["missing_read", "truncated", "save_after", "write_after", "gui_after"])
def test_stale_missing_and_partial_native_values(change):
    s = state()
    if change == "missing_read":
        del s.events[5]
    elif change == "truncated":
        s.events[5].result["context_hint"]["context_truncated"] = True
    elif change == "save_after":
        s.events.append(event(8, "workbook.save"))
    elif change == "write_after":
        s.events.append(event(8, "cells.set_formulas", {"sheet": "Data Set", "writes": [{"cell": "E8", "formula": "=0"}]}))
    else:
        e = event(8, "")
        e.proposed = {"kind": "gui"}
        s.events.append(e)
    assert any(i["code"] == "period.cells_unverified" for i in outcome_issues(s))


@pytest.mark.parametrize("key", ["data_series", "category_axes"])
def test_partial_chart_observation_is_unknown(key):
    s = state()
    del s.events[-1].result["context_hint"]["sheets"][0]["charts"][0][key]
    assert any(i["code"] == "period.chart_unverified" and i["kind"] == "missing_observation" for i in outcome_issues(s))


def test_wrong_title_and_chart_type():
    s = state()
    charts = s.events[-1].result["context_hint"]["sheets"][0]["charts"]
    charts[0]["title"] = "Something else"
    charts[1]["type"] = "bar"
    assert len([i for i in outcome_issues(s) if i["code"] == "period.chart_mismatch"]) == 2


def test_source_edit_cannot_silently_redefine_expected_totals():
    s = state()
    s.events.insert(3, event(3, "range.write", {"sheet": "Data Set", "range": "D5"}))
    s.events.append(read(8, "D5", [[99]]))
    assert any(v.get("cell") == "D5" for i in outcome_issues(s) if i["code"] == "period.values_mismatch" for v in i["observed"])


@pytest.mark.parametrize("instruction", [
    "Calculate growth percentage", INSTRUCTION.replace("month-on-month", "year-on-year"),
    INSTRUCTION.replace("Mar to Apr", "each month"), INSTRUCTION + " Use cumulative growth.",
])
def test_unsupported_instruction_is_unchanged(instruction):
    s = state()
    s.instruction = instruction
    assert request(instruction) is None
    assert outcome_issues(s) == []


def test_quarters_and_native_sheet_quoting():
    assert request(INSTRUCTION.replace("month", "quarter").replace("Mar to Apr", "Q2 to Q3"))["start"] == 1
    assert _range_cells("$'O''Brien'.$D$7:$E$7", "unused") == [("O'Brien", 4, 7), ("O'Brien", 5, 7)]


def test_ambiguous_source_and_other_domain_leave_existing_review():
    s = state()
    s.events[1].result["context_hint"]["values"][0][2] = "Feb"
    assert outcome_issues(s) == []
    s = state()
    s.domain = "os"
    assert outcome_issues(s) == []


def test_truncated_chart_inventory_does_not_claim_missing_title():
    s = state()
    s.events[-1].result["context_hint"]["sheets_omitted_from_context"] = 1
    issues = outcome_issues(s)
    assert [i["code"] for i in issues] == ["period.charts_unverified"]


def test_completion_gate_consumes_period_issues():
    from integrations.lite_agent.completion_outcomes import completion_outcome_issues

    s = state()
    s.events[5].result["context_hint"]["values"][1][2] = 50
    assert any(i["code"] == "period.values_mismatch" for i in completion_outcome_issues(s))


def test_read_of_other_document_is_not_native_proof():
    s = state()
    s.events[-1].result["context_hint"]["url"] = "file:///current.ods"
    s.events[5].result["context_hint"]["workbook_url"] = "file:///other.ods"
    assert any(i["code"] == "period.cells_unverified" for i in outcome_issues(s))


def test_zero_denominator_needs_user_policy():
    s = state()
    s.events[1].result["context_hint"]["values"][1][1] = 0
    s.events[1].result["context_hint"]["values"][2][1] = 0
    assert outcome_issues(s) == []
