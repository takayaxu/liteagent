"""Native font contracts preserve original styles and handle ties/unknown evidence."""
from copy import deepcopy

import pytest

from calc_adapter.uno_worker import _font_snapshot, _result_type
from integrations.lite_agent.adapter_results import adapter_context_hint
from integrations.lite_agent.calc_extremum_outcomes import _effective_color, _request, outcome_issues
from integrations.lite_agent.completion_outcomes import completion_outcome_issues
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState

INSTRUCTION = 'Calculate a new column with header "Score", convert the results as number type, and highlight the highest result with green (#00ff00) font.'


def font(color="#000000"):
    return {"font_color": color, "conditional_format": {"status": "known", "count": 0, "rules": []}}


def e(step, action, args, result):
    return ExecutionEvent(step=step, timestamp_utc="2031-01-01T00:00:00Z",
                          proposed={"kind": "adapter", "action": action, "arguments": args},
                          parsed=True, validated=True, executed=True, result={"context_hint": result})


def state(values=(2, 8, 8), colors=("#000000", "#00ff00", "#00ff00"), original=None,
          column="F", header_row=4, instruction=INSTRUCTION):
    header, area = f"{column}{header_row}", f"{column}{header_row + 1}:{column}{header_row + len(values)}"
    data = {"sheet": "Results", "range": area, "values": [[v] for v in values],
            "display_text": [[str(v)] for v in values], "kinds": [["formula"] for _ in values],
            "result_types": [["number"] for _ in values], "styles": [[font(c)] for c in colors],
            "number_formats": [[{"code": "0.00", "type": 16}] for _ in values]}
    before = deepcopy(data)
    before["styles"] = [[font(c)] for c in (original or ["#000000"] * len(values))]
    inventory = {"sheets": [{"name": "Results", "used_range_a1": f"B{header_row}:{column}{header_row + len(values)}"}]}
    return RuntimeState(task_id="extreme-contract", domain="libreoffice_calc", instruction=instruction, events=[
        e(1, "range.read", {"sheet": "Results", "range": area}, before),
        e(2, "range.write", {"sheet": "Results", "range": header},
          {"sheet": "Results", "range": header, "display_text": [["Score"]], "values": [["Score"]]}),
        e(3, "range.format", {"sheet": "Results", "range": area}, {}),
        e(4, "workbook.save", {}, {}), e(5, "workbook.inspect", {}, inventory),
        e(6, "range.read", {"sheet": "Results", "range": area}, data)])


def codes(s):
    return [i["code"] for i in outcome_issues(s)]


def test_ties_with_direct_font_and_alternate_layout():
    assert outcome_issues(state()) == []
    assert outcome_issues(state(column="AA", header_row=9)) == []
    assert completion_outcome_issues(state()) == []


def test_extra_new_color_reports_exact_non_extreme_cell():
    s = state(colors=("#00ff00", "#00ff00", "#00ff00"))
    issue = outcome_issues(s)[0]
    assert issue["code"] == "extremum.font_mismatch" and issue["kind"] == "state_mismatch"
    assert issue["observed"]["wrong_cells"][0]["cell"] == "F5"
    assert issue["expected"]["extreme_cells"] == ["F6", "F7"]


def test_preexisting_color_is_preserved():
    assert outcome_issues(state(colors=("#00ff00",) * 3, original=("#00ff00", "#000000", "#000000"))) == []


def test_missing_original_style_does_not_prescribe_reset():
    s = state(colors=("#00ff00",) * 3)
    del s.events[0].result["context_hint"]["styles"]
    assert codes(s) == ["extremum.styles_unverified"]


def test_missing_tied_highlight_and_minimum():
    assert codes(state(colors=("#000000", "#00ff00", "#000000"))) == ["extremum.font_mismatch"]
    s = state(values=(-8, -8, 3), colors=("#00ff00", "#00ff00", "#000000"), instruction=INSTRUCTION.replace("highest", "lowest"))
    assert outcome_issues(s) == []


@pytest.mark.parametrize("kind", [2, 4, 8, 256, 128, 512])
def test_number_request_rejects_date_percent_currency_text_formats(kind):
    s = state()
    s.events[-1].result["context_hint"]["number_formats"][0][0]["type"] = kind
    assert codes(s) == ["extremum.number_format_mismatch"]


@pytest.mark.parametrize("kind", [16, 17, 32, 64])
def test_numeric_format_precision_is_not_prescribed(kind):
    s = state()
    s.events[-1].result["context_hint"]["number_formats"][0][0]["type"] = kind
    assert outcome_issues(s) == []


@pytest.mark.parametrize("key", ["values", "kinds", "result_types", "styles", "number_formats"])
def test_missing_native_fields_are_unknown(key):
    s = state()
    del s.events[-1].result["context_hint"][key]
    assert outcome_issues(s)[0]["kind"] == "missing_observation"


@pytest.mark.parametrize("value", [True, "8", None, float("nan"), float("inf")])
def test_mixed_non_numeric_or_invalid_values_are_unknown(value):
    s = state()
    s.events[-1].result["context_hint"]["values"][0][0] = value
    assert codes(s) == ["extremum.values_unverified"]


def test_partial_stale_cross_document_and_error_formula_are_unknown():
    s = state()
    s.events[-1].result["context_hint"]["truncated"] = True
    assert outcome_issues(s)[0]["kind"] == "missing_observation"
    s = state()
    s.events.append(e(7, "cells.set_formulas", {"sheet": "Results", "writes": [{"cell": "B5", "formula": "=5"}]}, {}))
    assert codes(s) == ["extremum.column_unverified"]
    s = state()
    s.events[-1].result["context_hint"]["workbook_url"] = "file:///other.ods"
    s.events[-2].result["context_hint"]["url"] = "file:///current.ods"
    assert codes(s) == ["extremum.values_unverified"]
    s = state()
    s.events[-1].result["context_hint"]["result_types"][0][0] = "error"
    assert codes(s) == ["extremum.values_unverified"]


def cf_font():
    result = font()
    result["conditional_format"] = {"status": "known", "count": 1, "rules": [{
        "operator": "formula", "formula1": "$F5=MAX($F$5:$F$7)", "formula2": "0",
        "source_position": {"sheet": "Results", "column": 6, "row": 5}, "font_color": "#00ff00"}]}
    return result


def test_native_conditional_rule_is_an_equal_alternative_to_direct_font():
    s = state()
    s.events[-1].result["context_hint"]["styles"] = [[cf_font()] for _ in range(3)]
    assert outcome_issues(s) == []
    style = cf_font()
    assert _effective_color(style, "Results", 6, 5, 5, 7, 2, 8, "MAX") == "#000000"
    assert _effective_color(style, "Results", 6, 6, 5, 7, 8, 8, "MAX") == "#00ff00"


@pytest.mark.parametrize("change", ["source", "formula", "count", "status", "color", "rules", "formula2"])
def test_complex_or_missing_cf_evidence_is_unknown(change):
    style = cf_font()
    cf = style["conditional_format"]
    if change == "source":
        cf["rules"][0]["source_position"]["row"] = 4
    elif change == "formula":
        cf["rules"][0]["formula1"] = "$F5>7"
    elif change == "color":
        del cf["rules"][0]["font_color"]
    elif change == "formula2":
        cf["rules"][0]["formula2"] = "other"
    else:
        cf[change] = {"count": 2, "status": "unknown", "rules": []}[change]
    assert _effective_color(style, "Results", 6, 6, 5, 7, 8, 8, "MAX") is None


def test_duplicate_headers_and_multiple_table_extent_are_unknown():
    s = state()
    s.events.insert(2, e(2, "range.read", {"sheet": "Other", "range": "A1"}, {"values": [["Score"]], "display_text": [["Score"]]}))
    assert codes(s) == ["extremum.column_unverified"]
    s = state()
    s.events[-2].result["context_hint"]["sheets"][0]["used_range_a1"] = "B1:F7"
    assert codes(s) == ["extremum.extent_unverified"]


def test_mutation_before_establishes_style_but_late_baseline_cannot_hide_bad_formatting():
    s = state(colors=("#00ff00",) * 3)
    s.events.pop(0)
    before = {"sheet": "Results", "targets": [{"cell": "F5", "before": {"styles": font()}}]}
    s.events[0].result["context_hint"]["mutation_observation"] = before
    assert codes(s) == ["extremum.font_mismatch"]
    s.events[0].result["context_hint"].pop("mutation_observation")
    s.events.insert(2, e(3.5, "range.write", {"sheet": "Results", "range": "F5"}, {"mutation_observation": before}))
    assert codes(s) == ["extremum.styles_unverified"]


def test_unspecified_color_or_multiple_extrema_do_not_gain_contract():
    for instruction in (INSTRUCTION.replace("#00ff00", "green"), INSTRUCTION + " Also the lowest.", 'Make a chart.'):
        assert _request(instruction) is None


def test_read_context_preserves_native_styles_and_result_types():
    payload = state().events[-1].result["context_hint"]
    hint = adapter_context_hint("libreoffice_calc", "range.read", {"result": payload})
    assert hint["styles"] == payload["styles"] and hint["result_types"] == payload["result_types"]


def test_worker_missing_cf_and_error_results_are_explicit_unknown():
    class Cell:
        CharColor = -1
        FormulaResultType = "VALUE"

        def getError(self):
            return 522

    assert _font_snapshot(Cell())["conditional_format"]["status"] == "unknown"
    assert _font_snapshot(Cell())["font_color"] == "automatic"
    assert _result_type(Cell(), "formula") == "error"


@pytest.mark.parametrize("instruction", [
    'Calculate a new column with header "Score" and another new column with header "Rank"; highlight the highest result in "Rank" with green (#00ff00) font.',
    INSTRUCTION.replace('and highlight', 'and do not highlight'),
    INSTRUCTION.replace('and highlight', "and don't highlight"),
    INSTRUCTION.replace('and highlight', 'and optionally highlight'),
    'Calculate a new column with header "Score"; highlight the highest result with red font. Use #00ff00 background on the header.',
])
def test_ambiguous_negated_or_unrelated_color_contract_is_not_inferred(instruction):
    assert _request(instruction) is None
