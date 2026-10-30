from __future__ import annotations

from integrations.lite_agent.calc_monthly_summary import (
    source_monthly_totals,
    validate_monthly_totals,
)
from integrations.lite_agent.semantic_requirements import strict_semantic_requirement_errors
from integrations.lite_agent.completion import CompletionMixin
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


def _source(formulas: list[list[str]] | None = None) -> dict:
    return {
        "display_text": [
            ["Rep", "Jan", "Feb", "Mar"],
            ["Ada", "10", "20", "30"],
            ["Ben", "40", "50", "60"],
            ["Sum", "50", "70", "90"],
        ],
        "values": [
            ["Rep", "Jan", "Feb", "Mar"],
            ["Ada", 10, 20, 30],
            ["Ben", 40, 50, 60],
            ["Sum", 50, 70, 90],
        ],
        "formulas": formulas
        or [
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "=SUM(B2:B3)", "=SUM(C2:C3)", "=SUM(D2:D3)"],
        ],
        "kinds": [
            ["string", "string", "string", "string"],
            ["string", "number", "number", "number"],
            ["string", "number", "number", "number"],
            ["string", "formula", "formula", "formula"],
        ],
    }


def _target(totals: tuple[int, int, int]) -> dict:
    return {
        "display_text": [
            ["Month", "Total"],
            ["Jan", str(totals[0])],
            ["Feb", str(totals[1])],
            ["Mar", str(totals[2])],
        ],
        "values": [
            ["Month", "Total"],
            ["Jan", totals[0]],
            ["Feb", totals[1]],
            ["Mar", totals[2]],
        ],
        "formulas": [["", ""], ["", ""], ["", ""], ["", ""]],
        "kinds": [["string", "string"], ["string", "number"], ["string", "number"], ["string", "number"]],
    }


def test_excludes_sum_row_only_when_formula_aggregates_other_source_rows() -> None:
    months, totals, error = source_monthly_totals("Sales", "A1:D4", _source())

    assert error is None
    assert months == ["Jan", "Feb", "Mar"]
    assert totals == [50, 70, 90]


def test_external_aggregate_on_sum_label_is_not_excluded_and_refuses_completion() -> None:
    source = _source(
        [
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "=SUM(Other.B2:B3)", "=SUM(Other.C2:C3)", "=SUM(Other.D2:D3)"],
        ]
    )

    months, totals, error = source_monthly_totals("Sales", "A1:D4", source)

    assert error is not None and "external aggregate cannot classify" in error
    assert months == ["Jan", "Feb", "Mar"]
    assert totals == []


def test_current_row_only_aggregate_on_sum_label_is_not_excluded_and_refuses_completion() -> None:
    source = _source(
        [
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "=SUM(B4:B4)", "=SUM(C4:C4)", "=SUM(D4:D4)"],
        ]
    )

    months, totals, error = source_monthly_totals("Sales", "A1:D4", source)

    assert error is not None and "cannot classify" in error
    assert months == ["Jan", "Feb", "Mar"]
    assert totals == []


def test_unresolvable_sum_range_refuses_completion() -> None:
    source = _source(
        [
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "=SUM(B2:B)", "=SUM(C2:C3)", "=SUM(D2:D3)"],
        ]
    )

    months, _totals, error = source_monthly_totals("Sales", "A1:D4", source)

    assert months == ["Jan", "Feb", "Mar"]
    assert error is not None and "cannot classify" in error


def test_table_allows_formula_or_constant_values_but_rejects_extra_cells() -> None:
    target = _target((50, 70, 90))
    target["display_text"][1][1] = "50"
    target["formulas"][1][1] = "=SUM(Sales.B2:B3)"
    target["kinds"][1][1] = "formula"

    assert (
        validate_monthly_totals(
            source_sheet="Sales",
            source_range="A1:D4",
            source_result=_source(),
            target_headers=["Month", "Total"],
            target_range="A1:B4",
            comparison_precision=4,
            target_result=target,
        )
        is None
    )

    for field, blank in (("values", ""), ("display_text", ""), ("formulas", ""), ("kinds", "blank")):
        for row in target[field]:
            row.extend([blank] * 4)
    target["values"][0][2] = "=SUM(B2:B3)"
    target["display_text"][0][2] = "=SUM(B2:B3)"
    target["formulas"][0][2] = "=SUM(B2:B3)"
    target["kinds"][0][2] = "formula"
    assert (
        validate_monthly_totals(
            source_sheet="Sales",
            source_range="A1:D4",
            source_result=_source(),
            target_headers=["Month", "Total"],
            target_range="A1:F4",
            comparison_precision=4,
            target_result=target,
        )
        == "the new sheet contains non-empty cells outside the requested table"
    )


def test_synonymous_duplicate_month_headers_are_ambiguous() -> None:
    source = _source()
    source["display_text"][0] = ["Rep", "Jan", "January", "Mar"]
    source["values"][0] = ["Rep", "Jan", "January", "Mar"]

    months, _totals, error = source_monthly_totals("Sales", "A1:D4", source)

    assert months == []
    assert error is not None and "duplicate" in error


def test_multiple_month_header_rows_are_ambiguous() -> None:
    source = _source()
    source["display_text"][2] = ["Rep", "Jan", "Feb", "Mar"]
    source["values"][2] = ["Rep", "Jan", "Feb", "Mar"]

    months, _totals, error = source_monthly_totals("Sales", "A1:D4", source)

    assert months == []
    assert error is not None and "unique" in error


def test_non_numeric_text_is_not_coerced_to_a_number() -> None:
    source = _source()
    source["values"][1][1] = "USD 10"

    months, _totals, error = source_monthly_totals("Sales", "A1:D4", source)

    assert months == ["Jan", "Feb", "Mar"]
    assert error is not None and "non-numeric" in error


def test_strict_completion_semantics_reject_missing_monthly_table_evidence() -> None:
    instruction = 'Create a table with two column headers ("Month" and "Total") in a new sheet named "Sheet2" to show the total sales for all months.'
    state = RuntimeState(
        task_id="monthly-contract",
        domain="libreoffice_calc",
        instruction=instruction,
        events=[],
    )

    errors = strict_semantic_requirement_errors(state)

    assert any("monthly totals table lacks complete" in error for error in errors)


def _event(step: int, action: str, params: dict, payload: dict) -> ExecutionEvent:
    return ExecutionEvent(
        step=step,
        timestamp_utc="2030-01-01T00:00:00Z",
        proposed={"kind": "adapter", "action": action, "arguments": params},
        parsed=True,
        validated=True,
        executed=True,
        result={"context_hint": payload},
    )


def _completed_state() -> RuntimeState:
    source_sheet = {"name": "Sales", "used_range_a1": "A1:D4"}
    source = _source()
    target = {field: [] for field in ("display_text", "values", "formulas", "kinds")}
    table = _target((50, 70, 90))
    for row_index in range(9):
        for field in target:
            blank = "blank" if field == "kinds" else ""
            row = [blank] * 6
            if 2 <= row_index < 6:
                row[2:4] = table[field][row_index - 2]
            target[field].append(row)
    target_sheet = {"name": "Summary", "used_range_a1": "A1:F9"}
    return RuntimeState(
        task_id="monthly-flexible-output",
        domain="libreoffice_calc",
        instruction='Create a table with two column headers ("Month" and "Total") in a new sheet named "Summary" to show the total sales for all months.',
        events=[
            _event(1, "workbook.inspect", {}, {"sheets": [source_sheet]}),
            _event(2, "range.read", {"sheet": "Sales", "range": "A1:D4"}, source),
            _event(4, "range.write", {"sheet": "Summary", "range": "C3:D6", "values": table["values"]}, {"written_cells": 8}),
            _event(5, "workbook.save", {}, {"path": "/home/user/Sales.xlsx"}),
            _event(6, "workbook.inspect", {}, {"sheets": [source_sheet, target_sheet]}),
            _event(7, "range.read", {"sheet": "Summary", "range": "A1:F9"}, target),
        ],
    )


def _strict_gate(state: RuntimeState) -> dict:
    return CompletionMixin._generic_completion_gate(
        state,
        {"reason": "The new table has been saved and read back.", "evidence": ["Native table read-back is complete."]},
    )


def test_actual_strict_gate_accepts_non_a1_layout_with_blank_format_extension() -> None:
    assert _strict_gate(_completed_state())["passed"]


def test_actual_strict_gate_rejects_extra_formulas_like_original_failed_trajectory() -> None:
    state = _completed_state()
    target = state.events[-1].result["context_hint"]
    target["values"][1][5] = 50
    target["display_text"][1][5] = "50"
    target["formulas"][1][5] = "=SUM(Sales.B2:B3)"
    target["kinds"][1][5] = "formula"

    gate = _strict_gate(state)

    assert not gate["passed"]
    assert any("outside the requested table" in error for error in gate["missing"])


def test_summary_marker_without_range_formula_refuses_completion() -> None:
    source = _source()
    source["formulas"][-1] = ["", "", "", ""]
    months, totals, error = source_monthly_totals("Sales", "A1:D4", source)
    assert months == ["Jan", "Feb", "Mar"]
    assert totals == []
    assert error is not None and "cannot classify" in error


def test_summary_marker_with_description_uses_verified_source_ranges() -> None:
    source = _source()
    source["display_text"][-1][0] = "Total Sales"
    source["values"][-1][0] = "Total Sales"
    months, totals, error = source_monthly_totals("Sales", "A1:D4", source)
    assert error is None
    assert months == ["Jan", "Feb", "Mar"]
    assert totals == [50, 70, 90]


def test_min_named_detail_row_is_not_mistaken_for_summary() -> None:
    source = _source(
        [
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
        ]
    )
    source["display_text"][-1][0] = "Min"
    source["values"][-1][0] = "Min"

    months, totals, error = source_monthly_totals("Sales", "A1:D4", source)

    assert error is None
    assert months == ["Jan", "Feb", "Mar"]
    assert totals == [100, 140, 180]


def test_strict_gate_rejects_reads_before_later_source_or_target_changes() -> None:
    for sheet in ("Sales", "Summary"):
        state = _completed_state()
        state.events.append(_event(8, "range.write", {"sheet": sheet, "range": "F2", "values": [[99]]}, {}))
        gate = _strict_gate(state)
        assert not gate["passed"]
