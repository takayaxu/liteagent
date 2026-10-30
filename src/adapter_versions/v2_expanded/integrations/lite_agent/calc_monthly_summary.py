"""Evidence checks for a model-created monthly totals table."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .adapter_results import a1_geometry, column_number
from .observation_fields import display_rows, matrix_field


_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3,
    "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6,
    "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_CELL_REF = re.compile(
    r"(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_ ]*))\.)?\$?([A-Z]{1,3})\$?(\d+)",
    re.IGNORECASE,
)
_AGGREGATE = re.compile(r"(?i)=\s*(SUM|MIN|MAX|AVERAGE|COUNT|COUNTA|SUBTOTAL|AGGREGATE)\s*\(([^()]*)\)\s*")
_SUMMARY_LABEL = re.compile(
    r"(?i)\b(?:grand\s+total|sub\s*total|total|sum|minimum|maximum|average|avg|mean|min|max|count)\b"
)


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return None


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _source_summary_rows(
    *,
    sheet: str,
    geometry: tuple[int, int, int, int],
    rows: list[list[str]],
    formulas: list[list[Any]],
    header_index: int,
    month_columns: list[int],
) -> tuple[set[int] | None, str | None]:
    start_column_label, start_row, end_column_label, end_row = geometry
    start_column = column_number(start_column_label)
    summaries: set[int] = set()
    month_indices = set(month_columns)
    for row_index in range(header_index + 1, min(len(rows), end_row - start_row + 1)):
        labels = [
            str(value).strip().casefold()
            for value in rows[row_index][: min(month_columns)]
            if not _blank(value)
        ]
        marker_labels = [label for label in labels if _SUMMARY_LABEL.search(label)]
        if not marker_labels:
            continue
        source_row = start_row + row_index
        formula_row = formulas[row_index] if row_index < len(formulas) else []
        has_aggregate_formula = any(
            isinstance(formula, str)
            and re.search(
                r"(?i)\b(?:SUM|MIN|MAX|AVERAGE|COUNT|COUNTA|SUBTOTAL|AGGREGATE)\s*\(",
                formula,
            )
            for formula in formula_row
        )
        if "min" in marker_labels and not has_aggregate_formula:
            continue
        candidate_ranges: list[tuple[int, int, int]] = []
        has_ambiguous_aggregate = False
        has_external_reference = False
        for column_index in month_indices:
            formula = formula_row[column_index] if column_index < len(formula_row) else ""
            if not isinstance(formula, str) or not formula.startswith("="):
                has_ambiguous_aggregate = True
                continue
            aggregate = _AGGREGATE.fullmatch(formula.strip())
            if aggregate is None:
                has_ambiguous_aggregate = True
                continue
            refs = list(_CELL_REF.finditer(aggregate.group(2)))
            if len(refs) != 2 or "!" in aggregate.group(2):
                has_ambiguous_aggregate = True
                continue
            if aggregate.group(1).casefold() in {"subtotal", "aggregate"}:
                has_ambiguous_aggregate = True
                continue
            parsed: list[tuple[str | None, str, int]] = []
            for ref in refs:
                ref_sheet = ref.group(1) or ref.group(2)
                parsed.append((ref_sheet, ref.group(3).upper(), int(ref.group(4))))
            if any(ref_sheet and ref_sheet.casefold() != sheet.casefold() for ref_sheet, _, _ in parsed):
                has_external_reference = True
                continue
            if len({column for _, column, _ in parsed}) != 1:
                has_ambiguous_aggregate = True
                continue
            column = parsed[0][1]
            if column_number(column) != start_column + column_index:
                has_ambiguous_aggregate = True
                continue
            first_row, last_row = parsed[0][2], parsed[-1][2]
            if first_row > last_row:
                first_row, last_row = last_row, first_row
            if first_row < start_row + header_index + 1 or last_row > end_row:
                has_ambiguous_aggregate = True
                continue
            if first_row <= source_row <= last_row:
                has_ambiguous_aggregate = True
                continue
            candidate_ranges.append((column_index, first_row, last_row))
        if has_ambiguous_aggregate:
            return None, f"cannot classify {sheet} row {source_row} from its aggregate formula"
        if has_external_reference:
            return None, f"external aggregate cannot classify {sheet} row {source_row}"
        if candidate_ranges:
            ranges = {(first_row, last_row) for _, first_row, last_row in candidate_ranges}
            columns = {column_index for column_index, _, _ in candidate_ranges}
            if len(ranges) != 1 or columns != month_indices:
                return None, f"inconsistent source ranges on {sheet} row {source_row}"
            summaries.add(row_index)
    return summaries, None


def source_monthly_totals(
    sheet: str,
    cell_range: str,
    result: dict[str, Any],
) -> tuple[list[str], list[Decimal], str | None]:
    geometry = a1_geometry(cell_range)
    rows = display_rows(result)
    values = matrix_field(result, "values")
    formulas = matrix_field(result, "formulas")
    if geometry is None:
        return [], [], "the source read-back is incomplete"
    _start_column, start_row, _end_column, end_row = geometry
    expected_rows = end_row - start_row + 1
    expected_columns = column_number(_end_column) - column_number(_start_column) + 1
    if (
        not rows
        or len(rows) != expected_rows
        or len(values) != expected_rows
        or any(len(row) != expected_columns for row in rows)
        or any(len(row) != expected_columns for row in values)
    ):
        return [], [], "the source read-back is incomplete"
    header_candidates: list[tuple[int, list[str], list[int]]] = []
    for row_index, row in enumerate(rows):
        found = [
            (str(value).strip(), column_index)
            for column_index, value in enumerate(row)
            if str(value).strip().casefold() in _MONTHS
        ]
        canonical = [_MONTHS[month.casefold()] for month, _ in found]
        if len(found) >= 2 and len(set(canonical)) != len(canonical):
            return [], [], "duplicate or synonymous month headers are ambiguous"
        if len(found) >= 2 and len({column for _, column in found}) == len(found):
            header_candidates.append((row_index, [month for month, _ in found], [column for _, column in found]))
    if len(header_candidates) != 1:
        return [], [], "no unique monthly header row is observable"
    header_index, months, month_columns = header_candidates[0]
    summary_rows, error = _source_summary_rows(
        sheet=sheet,
        geometry=geometry,
        rows=rows,
        formulas=formulas,
        header_index=header_index,
        month_columns=month_columns,
    )
    if error:
        return months, [], error
    assert summary_rows is not None
    totals = [Decimal(0) for _ in month_columns]
    for row_index in range(header_index + 1, min(len(rows), end_row - start_row + 1)):
        if row_index in summary_rows:
            continue
        for index, column_index in enumerate(month_columns):
            value = values[row_index][column_index] if column_index < len(values[row_index]) else None
            if _blank(value):
                continue
            number = _number(value)
            if number is None:
                return months, [], f"non-numeric value in {sheet} row {start_row + row_index}"
            totals[index] += number
    return months, totals, None


def validate_monthly_totals(
    *,
    source_sheet: str,
    source_range: str,
    source_result: dict[str, Any],
    target_headers: list[str],
    target_range: str,
    comparison_precision: int,
    target_result: dict[str, Any],
) -> str | None:
    """Return a refusal reason, or None when the read-back proves the requested table."""
    months, totals, error = source_monthly_totals(source_sheet, source_range, source_result)
    if error:
        return error
    target_rows = display_rows(target_result)
    target_values = matrix_field(target_result, "values")
    target_geometry = a1_geometry(target_range)
    if target_geometry is None:
        return "the new sheet's used range is not a contiguous cell range"
    target_start_column, target_start_row, target_end_column, target_end_row = target_geometry
    target_expected_rows = target_end_row - target_start_row + 1
    target_expected_columns = column_number(target_end_column) - column_number(target_start_column) + 1
    if (
        not target_rows
        or len(target_rows) != target_expected_rows
        or len(target_values) != target_expected_rows
        or any(len(row) != target_expected_columns for row in target_rows)
        or any(len(row) != target_expected_columns for row in target_values)
    ):
        return "the new sheet has no complete read-back"
    headers = [str(value).strip().casefold() for value in target_headers]
    positions = [
        (row_index, column_index)
        for row_index, row in enumerate(target_rows)
        for column_index in range(max(0, len(row) - 1))
        if [str(row[column_index]).strip().casefold(), str(row[column_index + 1]).strip().casefold()]
        == headers
    ]
    if len(positions) != 1:
        return "the requested headers are missing or ambiguous on the new sheet"
    header_row, first_column = positions[0]
    if header_row + len(months) >= len(target_rows):
        return "the new table does not contain every observed month"
    expected_months = [month.casefold() for month in months]
    for offset, (month, expected_total) in enumerate(zip(expected_months, totals, strict=True), 1):
        row = target_rows[header_row + offset]
        values = target_values[header_row + offset]
        if first_column + 1 >= len(row) or first_column + 1 >= len(values):
            return "the new table is missing a month total"
        if str(row[first_column]).strip().casefold() != month:
            return "the new table months do not match the observed source columns"
        actual_total = _number(values[first_column + 1])
        if actual_total is None or round(actual_total, comparison_precision) != round(expected_total, comparison_precision):
            return f"the total for {month} does not match the observed source rows"
    table_cells = {
        (header_row + offset, first_column + column)
        for offset in range(len(months) + 1)
        for column in range(2)
    }
    formulas = matrix_field(target_result, "formulas")
    kinds = matrix_field(target_result, "kinds")
    for row_index in range(len(target_rows)):
        for column_index in range(len(target_rows[row_index])):
            if (row_index, column_index) in table_cells:
                continue
            value = target_values[row_index][column_index] if column_index < len(target_values[row_index]) else None
            formula = formulas[row_index][column_index] if row_index < len(formulas) and column_index < len(formulas[row_index]) else ""
            kind = kinds[row_index][column_index] if row_index < len(kinds) and column_index < len(kinds[row_index]) else "blank"
            if not _blank(value) or (isinstance(formula, str) and formula.strip()) or kind not in {"blank", "empty"}:
                return "the new sheet contains non-empty cells outside the requested table"
    return None
