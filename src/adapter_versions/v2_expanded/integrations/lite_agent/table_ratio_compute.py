"""Read-only ratio calculation over previously observed PDF tables."""

from __future__ import annotations

import math
import re
from typing import Any

from . import batch_table_semantics


TOOL_NAME = "table_ratio_matrix_compute"
ACTION = "table.ratio_matrix.compute"


def tool(state: Any) -> dict[str, Any]:
    paths = list(batch_table_semantics._successful_pdf_table_inspection_paths(state))
    source_paths = list(batch_table_semantics._observed_pdf_source_paths(state))
    layout = target_layout(state)
    source_schema: dict[str, Any] = {"type": "string"}
    if source_paths:
        source_schema["enum"] = sorted(source_paths)
    row_key_schema: dict[str, Any] = {"type": "string", "minLength": 1}
    column_schema: dict[str, Any] = {
        "type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1,
    }
    if layout is not None:
        row_key_schema["enum"] = layout["row_keys"]
        column_schema["items"]["enum"] = layout["column_keys"]
        column_schema["minItems"] = len(layout["column_keys"])
        column_schema["maxItems"] = len(layout["column_keys"])
    common_rows: set[str] | None = None
    for path in paths:
        labels = {
            str(row[0]).strip()
            for row in _observed_rows(state, path)
            if row and isinstance(row[0], str) and row[0].strip()
        }
        common_rows = labels if common_rows is None else common_rows.intersection(labels)
    row_options = sorted(
        label for label in common_rows or ()
        if _normalized(label) not in {"panel / subject discipline", "subject"}
    )
    row_schema: dict[str, Any] = {"type": "string", "minLength": 1}
    if row_options:
        row_schema["enum"] = row_options
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Calculate a read-only ratio matrix from successful pdf.tables.inspect results. "
                "Select each source and output year, the exact worksheet column order, "
                "and one exact first-column PDF row label. For an overall pass rate "
                "without a named discipline, select the observed aggregate Total row. "
                "Application and Supported are measure headers, never row labels. "
                "For a success/pass rate, use numerator=Supported and denominator=Application. "
                "Use line_index=0 for a single-number row. "
                + (
                    "Observed worksheet Year keys in order: " + repr(layout["row_keys"])
                    + "; exact column_keys: " + repr(layout["column_keys"]) + ". "
                    if layout is not None else ""
                )
                + "This does not write a workbook. Observed PDF paths: " + ", ".join(sorted(paths))
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "input_path": source_schema,
                                "row_key": row_key_schema,
                                "source_row_label": {
                                    "type": "string", "minLength": 1,
                                    "description": "Optional exact first-column row label for this PDF.",
                                },
                                "line_index": {
                                    "type": "integer", "minimum": 0,
                                    "description": "Optional numeric line index for this PDF.",
                                },
                                "source_column_keys": {
                                    "type": "array", "items": {"type": "string", "minLength": 1},
                                    "minItems": 1,
                                    "description": "Optional PDF header labels in output column order when a source uses different names.",
                                },
                            },
                            "required": ["input_path", "row_key"],
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                    },
                    "column_keys": column_schema,
                    "source_row_label": row_schema,
                    "line_index": {"type": "integer", "minimum": 0},
                    "numerator": {"type": "string", "minLength": 1},
                    "denominator": {"type": "string", "minLength": 1},
                },
                "required": [
                    "sources", "column_keys", "source_row_label",
                    "numerator", "denominator",
                ],
                "additionalProperties": False,
            },
        },
    }


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _header_aliases(value: str) -> set[str]:
    aliases = {_normalized(value)}
    if "/" in value or "(" in value:
        aliases.update(
            _normalized(part)
            for part in re.split(r"[/()]", value)
            if part.strip()
        )
    return aliases


def target_read_request(state: Any) -> dict[str, str] | None:
    """Return one bounded target rectangle copied from workbook.inspect."""
    probe = batch_table_semantics._valid_target_inspection(state)
    if probe is None:
        return None
    for mapping in batch_table_semantics._nested_mappings(getattr(probe, "result", None)):
        sheets = mapping.get("sheets")
        if not isinstance(sheets, list):
            continue
        for sheet_entry in sheets:
            if not isinstance(sheet_entry, dict) or not isinstance(sheet_entry.get("name"), str):
                continue
            used = sheet_entry.get("used_range_a1")
            if not isinstance(used, str):
                coordinates = sheet_entry.get("used_range")
                if not isinstance(coordinates, dict):
                    continue
                start_row = coordinates.get("start_row")
                end_row = coordinates.get("end_row")
                start_column = coordinates.get("start_column")
                end_column = coordinates.get("end_column")
                if not all(isinstance(value, int) for value in (start_row, end_row, start_column, end_column)):
                    continue
                used = (
                    f"{batch_table_semantics.column_label(start_column + 1)}{start_row + 1}:"
                    f"{batch_table_semantics.column_label(end_column + 1)}{end_row + 1}"
                )
            geometry = batch_table_semantics.a1_geometry(used)
            if geometry is None:
                continue
            start_column, start_row, end_column, end_row = geometry
            cells = (batch_table_semantics.column_number(end_column) - batch_table_semantics.column_number(start_column) + 1) * (end_row - start_row + 1)
            if end_row - start_row + 1 > 1000 or cells > 10000:
                continue
            return {"sheet": sheet_entry["name"], "range": used}
    return None


def target_layout(state: Any) -> dict[str, Any] | None:
    """Read row and column keys from bounded Calc observations when present."""
    probe = batch_table_semantics._valid_target_inspection(state)
    if probe is None:
        return None
    for event in reversed(batch_table_semantics._successful_action_events(state, "range.read")):
        if event.step <= probe.step:
            continue
        params = batch_table_semantics._batch_arguments(event, state)
        cell_range = params.get("range")
        sheet = params.get("sheet")
        geometry = batch_table_semantics.a1_geometry(str(cell_range or ""))
        if geometry is None or not isinstance(sheet, str):
            continue
        for mapping in batch_table_semantics._nested_mappings(getattr(event, "result", None)):
            rows = mapping.get("display_text")
            if not isinstance(rows, list) or len(rows) < 2 or not all(isinstance(row, list) for row in rows):
                continue
            header = [str(value or "").strip() for value in rows[0]]
            if len(header) < 2 or _normalized(header[0]) != "year":
                continue
            columns = [value for value in header[1:] if value]
            if not columns or len(columns) != len(header) - 1:
                continue
            keys = [str(row[0]).strip() for row in rows[1:] if row and str(row[0]).strip()]
            if len(keys) != len(rows) - 1 or len(set(keys)) != len(keys):
                continue
            start_column, start_row, _end_column, _end_row = geometry
            first_column = batch_table_semantics.column_label(
                batch_table_semantics.column_number(start_column) + 1
            )
            last_column = batch_table_semantics.column_label(
                batch_table_semantics.column_number(start_column) + len(columns)
            )
            return {
                "sheet": sheet, "row_keys": keys, "column_keys": columns,
                "range": f"{first_column}{start_row + 1}:{last_column}{start_row + len(keys)}",
            }
    return None


def _observed_rows(state: Any, path: str) -> list[list[Any]]:
    for event in reversed(batch_table_semantics._successful_action_events(state, "pdf.tables.inspect")):
        if batch_table_semantics._batch_arguments(event, state).get("input_path") != path:
            continue
        for mapping in batch_table_semantics._nested_mappings(getattr(event, "result", None)):
            rows = mapping.get("rows")
            if isinstance(rows, list) and rows and all(isinstance(row, list) for row in rows):
                return rows
    raise ValueError(f"no successful native table observation contains {path!r}")


def _number_at(value: Any, line_index: int, path: str, column: str) -> int:
    lines = str(value).splitlines() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else []
    if line_index >= len(lines):
        raise ValueError(f"{path}: {column} has no numeric line {line_index}")
    match = re.fullmatch(r"\s*([0-9][0-9,]*)\s*", lines[line_index])
    if match is None:
        raise ValueError(f"{path}: {column} line {line_index} is not an observed integer")
    return int(match.group(1).replace(",", ""))


def compute(state: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    if not batch_table_semantics.native_pdf_table_observation_complete(state):
        raise ValueError("observe every discovered PDF table before computing ratios")
    if batch_table_semantics._valid_target_inspection(state) is None:
        raise ValueError("inspect the live target workbook before computing ratios")
    layout = target_layout(state)
    if layout is None:
        raise ValueError("read the target workbook range with its Year and column headers first")
    sources = arguments["sources"]
    columns = arguments["column_keys"]
    paths = [source["input_path"] for source in sources]
    keys = [source["row_key"] for source in sources]
    if len(set(paths)) != len(paths) or len(set(keys)) != len(keys):
        raise ValueError("sources must have unique input_path and row_key values")
    if keys != layout["row_keys"]:
        raise ValueError("source row_keys must exactly match the observed worksheet Year column in order")
    if columns != layout["column_keys"]:
        raise ValueError("column_keys must exactly match observed worksheet headers in order")
    observed_paths = set(batch_table_semantics._observed_pdf_source_paths(state))
    if observed_paths and set(paths) != observed_paths:
        raise ValueError("sources must cover every discovered PDF exactly once")
    if len(set(map(_normalized, columns))) != len(columns):
        raise ValueError("column_keys must be unique")
    numerator = _normalized(arguments["numerator"])
    denominator = _normalized(arguments["denominator"])
    if numerator == denominator:
        raise ValueError("numerator and denominator must identify different measures")
    values: list[list[float]] = []
    provenance: list[dict[str, Any]] = []
    for source in sources:
        path = source["input_path"]
        source_columns = source.get("source_column_keys", columns)
        if len(source_columns) != len(columns):
            raise ValueError(f"{path}: source_column_keys must match column_keys length")
        rows = _observed_rows(state, path)
        subject = _normalized(source.get("source_row_label", arguments["source_row_label"]))
        line_index = source.get("line_index", arguments.get("line_index", 0))
        subject_rows = [row for row in rows if row and subject == _normalized(row[0])]
        if len(subject_rows) != 1:
            labels = [str(row[0]).strip().replace("\n", " ")[:100] for row in rows if row and row[0]]
            raise ValueError(
                f"{path}: source_row_label must equal one first-column row label; "
                f"Application/Supported are measure headers. Observed labels: {labels[:15]}"
            )
        subject_row = subject_rows[0]
        header = rows[0]
        measures = rows[1] if len(rows) > 1 else []
        units = rows[2] if len(rows) > 2 else []
        result_row: list[float] = []
        for column, source_column in zip(columns, source_columns):
            starts = [index for index, label in enumerate(header) if _normalized(label) == _normalized(source_column)]
            if not starts and ("/" in source_column or "(" in source_column):
                aliases = _header_aliases(source_column)
                starts = [index for index, label in enumerate(header) if _normalized(label) in aliases]
            if len(starts) != 1:
                raise ValueError(f"{path}: column {column!r} must identify one observed header")
            start = starts[0]
            end = next((index for index in range(start + 1, len(header)) if _normalized(header[index])), len(header))
            measure_columns = {}
            for index in range(start, end):
                measure = _normalized(measures[index]) if index < len(measures) else ""
                unit = _normalized(units[index]) if index < len(units) else ""
                if measure and unit in {"no", "number", "count"}:
                    measure_columns[measure] = index
            if numerator not in measure_columns or denominator not in measure_columns:
                raise ValueError(f"{path}: {column} lacks observed {denominator} and {numerator} count columns")
            numerator_count = _number_at(subject_row[measure_columns[numerator]], line_index, path, column)
            denominator_count = _number_at(subject_row[measure_columns[denominator]], line_index, path, column)
            if numerator_count > denominator_count:
                raise ValueError(f"{path}: {column} numerator exceeds denominator")
            if denominator_count == 0 and numerator_count != 0:
                raise ValueError(f"{path}: {column} has a zero denominator")
            ratio = 0.0 if denominator_count == 0 else numerator_count / denominator_count
            if not math.isfinite(ratio):
                raise ValueError(f"{path}: {column} produced a non-finite ratio")
            result_row.append(ratio)
            provenance.append({
                "row_key": source["row_key"], "column_key": column,
                "input_path": path, "numerator_count": numerator_count,
                "denominator_count": denominator_count,
            })
        values.append(result_row)
    return {
        "status": "ok", "executed": True,
        "row_keys": keys, "column_keys": columns, "values": values,
        "numerator": arguments["numerator"],
        "denominator": arguments["denominator"],
        "provenance": provenance,
    }


def latest_result(state: Any) -> dict[str, Any] | None:
    for event in reversed(getattr(state, "events", ())):
        proposed = getattr(event, "proposed", None)
        if (
            getattr(event, "executed", False)
            and isinstance(proposed, dict)
            and proposed.get("action") == ACTION
            and isinstance(getattr(event, "result", None), dict)
        ):
            return event.result
    return None
