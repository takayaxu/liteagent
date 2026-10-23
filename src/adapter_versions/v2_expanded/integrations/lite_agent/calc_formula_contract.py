"""Model-owned expressions and native evidence for annual-change tables.

No formula or destination is generated here. The instruction supplies the
operation and labels; observed cells supply source identity and values.
"""

from __future__ import annotations

import math
import re

from calc_adapter.errors import AdapterError
from calc_adapter.schema import orient_typed_values

from .completion_policy import (
    action_is_read_only,
    action_is_save,
    effective_canonical_action,
)
from .completion_outcomes import rectangle, result_payload, _issue
from .instruction_semantics import requested_annual_percentage_change_summary

ACTIONS = (
    "workbook.inspect",
    "range.read",
    "range.write",
    "cells.set_formulas",
    "range.format",
    "workbook.save",
)
GUIDANCE = (
    " Calculated annual changes must be model-authored Calc formulas with explicit "
    "sheet-qualified references to the observed current and previous year cells. "
    "Do not calculate a number in prose and write it as a literal. Use "
    "cells.set_formulas with one explicit {cell,formula} record per calculated cell. "
    "Use range.write for literal headers and requested year labels. "
    "Write headers and every requested year label first so each "
    "target is identifiable. Calc evaluates the expression; inspect its returned "
    "formulas, numeric values and errors. Store fractional ratios for percentage "
    "display. Save and range.read the final output after changes; input sufficiency "
    "does not establish calculation correctness."
)
REF = re.compile(
    r"(?<![\w.])(?:\$?(?:'((?:[^']|'')+)'|([A-Za-z_][\w ]*))\s*[.!])?"
    r"\$?([A-Za-z]{1,4})\$?([1-9]\d*)(?![\w])"
)


def request(state):
    return (
        requested_annual_percentage_change_summary(state.instruction)
        if state.domain == "libreoffice_calc"
        else None
    )


def numeric(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _label(value):
    return " ".join(str(value).strip().casefold().split())


def _column(number):
    text = ""
    while number:
        number, index = divmod(number - 1, 26)
        text = chr(65 + index) + text
    return text


def _coordinate(column, row):
    return f"{_column(column)}{row}"


def _literal(value):
    if isinstance(value, dict):
        return (
            value.get("value")
            if value.get("kind") not in {"formula", "formatted_text"}
            else None
        )
    return value


def _proposed_cells(action, args):
    if action == "cells.set_formulas":
        for write in args.get("writes", []):
            rect = rectangle(write.get("cell"))
            if rect:
                yield (
                    (rect[0], rect[1]),
                    {"kind": "formula", "value": write.get("formula")},
                )
    elif action == "range.write":
        rect, values = rectangle(args.get("range")), args.get("values")
        if not rect or not isinstance(values, list) or not values:
            return
        try:
            values = orient_typed_values(
                values,
                target_rows=rect[3] - rect[1] + 1,
                target_columns=rect[2] - rect[0] + 1,
            )
        except AdapterError:
            return  # Malformed rectangles cannot establish any cell identity.
        for ri, row in enumerate(values):
            if isinstance(row, list):
                for ci, value in enumerate(row):
                    yield (rect[0] + ci, rect[1] + ri), value


def _invalidate(grid, rect=None):
    for key, cell in grid.items():
        if (
            rect is None
            or rect[0] <= key[0] <= rect[2]
            and rect[1] <= key[1] <= rect[3]
        ):
            cell["native"] = False


def _observe(grids, event, args, document=None):
    payload = result_payload(event)
    if document and payload.get("workbook_url") and payload["workbook_url"] != document:
        return
    sheet = payload.get("sheet", args.get("sheet"))
    area = payload.get("range", args.get("range"))
    if sheet != args.get("sheet") or (args.get("range") and area != args["range"]):
        return
    rect, values = rectangle(area), payload.get("values")
    if (
        not sheet
        or not rect
        or not isinstance(values, list)
        or any(
            payload.get(k)
            for k in ("truncated", "context_truncated", "source_truncated")
        )
        or len(values) != rect[3] - rect[1] + 1
        or any(
            not isinstance(row, list) or len(row) != rect[2] - rect[0] + 1
            for row in values
        )
    ):
        return
    formulas, kinds = payload.get("formulas", []), payload.get("kinds", [])
    display = payload.get("display_text", [])
    grid = grids.setdefault(sheet, {})

    def item(matrix, ri, ci):
        return (
            matrix[ri][ci]
            if ri < len(matrix)
            and isinstance(matrix[ri], list)
            and ci < len(matrix[ri])
            else None
        )

    for ri, row in enumerate(values):
        for ci, value in enumerate(row):
            grid[(rect[0] + ci, rect[1] + ri)] = {
                "value": value,
                "formula": item(formulas, ri, ci),
                "kind": item(kinds, ri, ci),
                "display": item(display, ri, ci),
                "step": event.step,
                "native": True,
            }


def _grids(state, candidate=None):
    grids = {}
    last_change = last_save = 0
    document = None
    for event in state.events:
        if event.proposed.get("kind") == "gui":
            for grid in grids.values():
                _invalidate(grid)
            last_change = event.step
            continue
        if event.proposed.get("kind") != "adapter":
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        if domain != "libreoffice_calc":
            continue
        if event.executed and action in {"workbook.open", "workbook.create_new"}:
            grids = {}
            last_change = event.step
            last_save = 0
        if event.executed and action == "workbook.inspect":
            url = result_payload(event).get("url")
            if document and url and document != url:
                grids = {}
            document = url or document
        mutates = not action_is_read_only(action) and not action_is_save(action)
        if mutates and (event.executed or event.validated):
            last_change = event.step
            sheet = args.get("sheet")
            if sheet:
                _invalidate(grids.setdefault(sheet, {}), rectangle(args.get("range")))
            elif action not in {"sheet.create", "workbook.open", "workbook.create_new"}:
                for grid in grids.values():
                    _invalidate(grid)
        if not event.executed or event.error:
            continue
        if action_is_save(action):
            last_save = event.step
        if action in {"range.write", "cells.set_formulas"}:
            grid = grids.setdefault(args.get("sheet"), {})
            for coordinate, value in _proposed_cells(action, args):
                grid[coordinate] = {
                    "value": _literal(value),
                    "native": False,
                    "step": event.step,
                }
        if action in {"range.read", "range.write", "cells.set_formulas"}:
            _observe(grids, event, args, document)
    if candidate:
        action, args = candidate
        grid = grids.setdefault(args.get("sheet"), {})
        for coordinate, value in _proposed_cells(action, args):
            if not isinstance(value, dict) or value.get("kind") != "formula":
                grid[coordinate] = {"value": _literal(value), "native": False}
    return grids, last_change, last_save


def _layout(grid, headers):
    candidates = []
    for row in sorted({row for _, row in grid}):
        columns = []
        for header in headers:
            matches = [
                c
                for (c, r), cell in grid.items()
                if r == row and _label(cell.get("value")) == _label(header)
            ]
            if len(matches) != 1:
                break
            columns.append(matches[0])
        if len(columns) == len(headers):
            candidates.append((row, columns))
    return candidates[0] if len(candidates) == 1 else None


def _years(grid, header_row, column):
    result = {}
    for (c, row), cell in grid.items():
        value = cell.get("value")
        if (
            c == column
            and row > header_row
            and re.fullmatch(r"\d{4}(?:\.0+)?", str(value))
        ):
            year = int(float(value))
            if year in result:
                return {}  # Duplicate years are ambiguous, not the last row wins.
            result[year] = row
    return result


def _sources(grids, spec):
    candidates = []
    headers = [spec["output_headers"][0], *spec["source_headers"]]
    for sheet, grid in grids.items():
        if sheet == spec["target_sheet"] or not (layout := _layout(grid, headers)):
            continue
        header_row, columns = layout
        years = _years(grid, header_row, columns[0])
        required_years = range(spec["start_year"] - 1, spec["end_year"] + 1)
        required = [(c, header_row) for c in columns] + [
            (c, years[y]) for y in required_years if y in years for c in columns
        ]
        if all(y in years for y in required_years) and all(
            grid[key].get("native") for key in required
        ):
            candidates.append((sheet, grid, columns, years))
    return candidates[0] if len(candidates) == 1 else None


def _targets(grid, spec):
    layout = _layout(grid, spec["output_headers"])
    if not layout:
        return {}
    header_row, columns = layout
    years = _years(grid, header_row, columns[0])
    return {
        (column, years[y]): (y, index)
        for y in range(spec["start_year"], spec["end_year"] + 1)
        if y in years
        for index, column in enumerate(columns[1:])
    }


def _label_evidence(grid, spec):
    """Report observed layout and missing labels without choosing a destination."""
    layout = _layout(grid, spec["output_headers"])
    years = _years(grid, layout[0], layout[1][0]) if layout else {}
    required = list(range(spec["start_year"], spec["end_year"] + 1))
    return {
        "required_headers": spec["output_headers"],
        "headers_observed": layout is not None,
        "observed_year_column": _column(layout[1][0]) if layout else None,
        "observed_year_cells": {str(y): _coordinate(layout[1][0], row) for y, row in years.items()} if layout else {},
        "missing_year_labels": [year for year in required if year not in years],
        "ready_for_formulas": bool(layout) and all(year in years for year in required),
    }


def _references(formula, destination):
    # Text literals, ranges and external/indirect references need a richer
    # provenance contract; do not silently count their apparent cell tokens.
    if (
        not isinstance(formula, str)
        or not formula.startswith("=")
        or any(c in formula for c in ('"', ":", "[", "]"))
    ):
        return set()
    return {
        (a.replace("''", "'") if a else b or destination, f"{column.upper()}{row}")
        for a, b, column, row in REF.findall(formula)
    }


def _required_refs(source, year, index):
    sheet, _, columns, years = source
    column = columns[index + 1]
    return {(sheet, _coordinate(column, years[y])) for y in (year - 1, year)}


def argument_errors(state, action, args):
    spec = request(state)
    if (
        not spec
        or action not in {"range.write", "cells.set_formulas"}
        or args.get("sheet") != spec["target_sheet"]
    ):
        return []
    if action == "range.write" and (rect := rectangle(args.get("range"))):
        try:
            orient_typed_values(
                args.get("values"),
                target_rows=rect[3] - rect[1] + 1,
                target_columns=rect[2] - rect[0] + 1,
            )
        except AdapterError as exc:
            detail = (
                "For a one-column target use a flat list or one value per nested row, "
                "not one nested row containing every value. "
                if rect[0] == rect[2] and rect[1] != rect[3]
                else "For a rectangular target use one nested list per worksheet row. "
            )
            return [
                f"{exc.code}: {exc.message} Target dimensions are "
                f"{rect[3] - rect[1] + 1} rows by {rect[2] - rect[0] + 1} columns. "
                + detail
                + "Validate the matrix shape before interpreting cell roles. No cells were written."
            ]
    grids, _, _ = _grids(state, (action, args))
    grid = grids[spec["target_sheet"]]
    targets, source = _targets(grid, spec), _sources(grids, spec)
    layout = _layout(grid, spec["output_headers"])
    errors = []
    string_formulas = []
    for coordinate, value in _proposed_cells(action, args):
        literal = _literal(value)
        if isinstance(value, dict) and value.get("kind") == "formula":
            if coordinate not in targets:
                labels = _label_evidence(grid, spec)
                errors.append(
                    "Write the requested output headers and year labels first, so each formula target is identifiable. "
                    f"Missing year labels: {labels['missing_year_labels']}; "
                    f"observed year column: {labels['observed_year_column']}. "
                    "Use range.write with literal labels before retrying cells.set_formulas. "
                    "This call wrote no cells."
                )
            elif source is None:
                errors.append(
                    "Read the source year labels, requested column headers and numeric values including the prior year before calculation"
                )
            elif _references(
                value.get("value"), spec["target_sheet"]
            ) != _required_refs(source, *targets[coordinate]):
                errors.append(
                    f"{_coordinate(*coordinate)} source reference mismatch: "
                    f"observed {sorted(_references(value.get('value'), spec['target_sheet']))}; "
                    f"required {sorted(_required_refs(source, *targets[coordinate]))}. "
                    "Bind the requested year to the source year label; source rows and destination rows are independent. "
                    "Qualify source references with their actual sheet name."
                )
        elif isinstance(value, dict) and value.get("kind") == "formatted_text":
            errors.append(
                "Calculated outputs require native numeric formulas, not formatted text composition"
            )
        elif literal is not None:
            year_label = (
                layout
                and coordinate[0] == layout[1][0]
                and re.fullmatch(r"\d{4}(?:\.0+)?", str(literal))
                and spec["start_year"] <= int(float(literal)) <= spec["end_year"]
            )
            if isinstance(literal, str) and literal.startswith("="):
                string_formulas.append(_coordinate(*coordinate))
                continue
            if coordinate in targets or (
                (
                    isinstance(literal, (int, float))
                    or re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", str(literal))
                )
                and not year_label
            ):
                errors.append(
                    f"{_coordinate(*coordinate)} is a calculated output: submit a typed Calc formula with observed source references, not a precomputed literal"
                )
    if string_formulas:
        errors.insert(
            0,
            "range.write formula strings are literal text at "
            + ", ".join(string_formulas[:6])
            + (
                f" and {len(string_formulas) - 6} more cells"
                if len(string_formulas) > 6
                else ""
            )
            + '. Use typed {"kind":"formula","value":"=<your expression>"} cells, '
            "or cells.set_formulas; qualify the actual source sheet. "
            "This entire call was rejected before execution, so none of its year labels or values were written.",
        )
    unique = list(dict.fromkeys(errors))
    if len(unique) > 4:
        unique = [
            *unique[:4],
            f"{len(unique) - 4} additional cells violate the same calculation contract; correct the entire batch.",
        ]
    return unique


def constrain_tool(function, state):
    if not request(state) or function.get("name") not in {
        "adapter__range_write",
        "adapter__cells_set_formulas",
    }:
        return
    if GUIDANCE.strip() not in function["description"]:
        function["description"] = GUIDANCE.strip() + " " + function["description"]
    if function["name"] == "adapter__range_write":
        values = function["parameters"]["properties"]["values"]
        prefix = (
            "Write literal headers and year labels only with this tool. "
            "For formulas use cells.set_formulas with explicit cell addresses; "
            "do not put formula strings or typed formula objects in values. "
        )
        # The XML grammar does not reliably constrain nested typed cells. Keep
        # the literal writer simple and put model-owned expressions through the
        # public address/formula record API. The Adapter still accepts typed
        # matrices from other callers; no rejected matrix is silently reshaped.
        literal = {"type": ["string", "number", "boolean", "null"]}
        values["items"] = {"oneOf": [
            literal,
            {"type": "array", "minItems": 1, "items": literal},
        ]}
        if not values.get("description", "").startswith(prefix):
            values["description"] = (
                prefix + "For a single row or column use a flat list; "
                "for a rectangle supply one nested list per worksheet row, "
                "matching the A1 target dimensions exactly. "
                "A failed call wrote none of its labels."
            )


def constrain_tools(tools, state):
    """Keep formula writes behind their existing label evidence dependency.

    This is surface selection from the current event ledger, not another
    audit. Reads and literal repair remain available; lost/missing labels
    immediately reopen the dependency instead of relying on call counts.
    """
    spec = request(state)
    if not spec:
        return tools
    grids, _, _ = _grids(state)
    labels = _label_evidence(grids.get(spec["target_sheet"], {}), spec)
    for tool in tools:
        function = tool.get("function", {})
        constrain_tool(function, state)
        if function.get("name") == "adapter__range_write" and not labels["ready_for_formulas"]:
            function["description"] += (
                " Before calculations, complete the literal layout. "
                f"Required headers: {labels['required_headers']}; "
                f"headers observed: {labels['headers_observed']}; "
                f"missing year labels: {labels['missing_year_labels']}; "
                f"observed year column: {labels['observed_year_column']}."
            )
    if labels["ready_for_formulas"]:
        return tools
    return [tool for tool in tools if tool.get("function", {}).get("name") != "adapter__cells_set_formulas"]


def model_evidence(state, limit=24):
    """Project native labels/addresses, never a generated expression or answer.

    Keep this outside history compaction so a rejection cannot erase the
    evidence needed to correct source/destination row and worksheet confusion.
    """
    spec = request(state)
    if not spec:
        return None
    grids, _, _ = _grids(state)
    source = _sources(grids, spec)
    if source is None:
        return None
    sheet, grid, columns, years = source
    target_grid = grids.get(spec["target_sheet"], {})
    targets = {
        value: _coordinate(*coordinate)
        for coordinate, value in _targets(target_grid, spec).items()
    }
    pairs = []
    for year in range(spec["start_year"], spec["end_year"] + 1):
        for index, header in enumerate(spec["source_headers"]):
            column = columns[index + 1]
            pairs.append(
                {
                    "year": year,
                    "source_column": header,
                    "current": {
                        "sheet": sheet,
                        "cell": _coordinate(column, years[year]),
                        "value": grid[(column, years[year])]["value"],
                    },
                    "previous": {
                        "sheet": sheet,
                        "cell": _coordinate(column, years[year - 1]),
                        "value": grid[(column, years[year - 1])]["value"],
                    },
                    "observed_destination": targets.get((year, index)),
                }
            )
    return {
        "source": "native_cell_observations",
        "destination_sheet": spec["target_sheet"],
        "year_column_observed": bool(targets),
        "destination_labels": _label_evidence(target_grid, spec),
        "pairs": pairs[:limit],
        "omitted_pairs": max(0, len(pairs) - limit),
        "guidance": "These are observed source cells and existing destination labels, not executed formulas. "
        "Write missing literal headers and every missing year label with range.write first. "
        "Then use cells.set_formulas with one explicit cell/formula record per destination. "
        "Choose your own expression and target using these facts. A rejected batch wrote none of its labels or values.",
    }


def outcome_issues(state):
    spec = request(state)
    if not spec:
        return []
    grids, changed, saved = _grids(state)
    # Initial inspection/reading remains owned by the normal tool surface.
    if not changed:
        return []

    def issue(code, expected, observed=None, mismatch=False):
        return [
            _issue(
                "calculation." + code,
                {"sheet": spec["target_sheet"]},
                expected,
                observed,
                actions=ACTIONS,
                mismatch=mismatch,
            )
        ]

    source = _sources(grids, spec)
    if source is None:
        return issue(
            "source_unverified",
            "unambiguous native source labels and values covering each requested year and its predecessor",
        )
    grid = grids.get(spec["target_sheet"], {})
    targets = _targets(grid, spec)
    needed = (spec["end_year"] - spec["start_year"] + 1) * len(spec["source_headers"])
    if len(targets) != needed:
        return issue(
            "layout_incomplete",
            "model-selected output headers and one row for every requested year",
        )
    wrong = []
    for coordinate, (year, index) in targets.items():
        cell = grid.get(coordinate, {})
        if not cell.get("native"):
            return issue(
                "output_unverified",
                "native range.read of all calculated outputs after final mutation and save",
            )
        refs = _references(cell.get("formula"), spec["target_sheet"])
        required = _required_refs(source, year, index)
        _, source_grid, columns, years = source
        current = source_grid[(columns[index + 1], years[year])]["value"]
        previous = source_grid[(columns[index + 1], years[year - 1])]["value"]
        value = cell.get("value")
        if not numeric(current) or not numeric(previous) or previous == 0:
            return issue(
                "source_undefined",
                "finite numeric inputs and a nonzero previous-year denominator",
                {"year": year, "column": spec["source_headers"][index]},
            )
        expected = (current - previous) / previous
        if (
            refs != required
            or cell.get("kind") != "formula"
            or not numeric(value)
            or not math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-12)
        ):
            wrong.append(
                {
                    "cell": _coordinate(*coordinate),
                    "year": year,
                    "source_column": spec["source_headers"][index],
                    "observed_value": value,
                    "observed_formula": cell.get("formula"),
                    "required_source_refs": sorted(required),
                    "required_ratio": expected,
                }
            )
    if wrong:
        return issue(
            "output_mismatch",
            "native formulas using the correct source years and column, with matching Calc numeric results",
            wrong,
            True,
        )
    header_row, columns = _layout(grid, spec["output_headers"])
    years = _years(grid, header_row, columns[0])
    # The final post-save readback is scoped to calculated outputs.  Headers
    # and year labels are immutable layout evidence established before the
    # save; requiring them to be reread after saving rejects a valid final
    # read such as B2:D6 and can trap the model in a save/read loop.
    if saved <= changed or any(
        not grid[c].get("native") or grid[c]["step"] <= saved
        for c in targets
    ):
        return issue(
            "final_readback_missing",
            "save after final mutation, then read the final calculated scope",
        )
    if any(not str(grid[c].get("display", "")).strip().endswith("%") for c in targets):
        return issue(
            "display_unverified",
            "native percentage display for the calculated fractional results",
        )
    if any(
        grid[(columns[0], row)].get("native")
        and str(grid[(columns[0], row)].get("display", "")).strip() != str(year)
        for year, row in years.items()
    ):
        return issue(
            "year_display_mismatch", "year labels displayed as years, not percentages"
        )
    return []
