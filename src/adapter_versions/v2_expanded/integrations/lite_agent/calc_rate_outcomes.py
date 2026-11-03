"""Observe simple annual-to-period rates without authoring model formulas."""
from __future__ import annotations

import math
import re

from .completion_outcomes import _alias, _complete_rows, _events, _issue, _same_document, _used_rectangle, rectangle
from .calc_scaled_outcomes import _cells, _column, _source_touched
from .instruction_semantics import requested_period_rate_column
from .completion_policy import action_is_read_only, action_is_save

ACTIONS = ("workbook.inspect", "range.read", "range.write", "cells.set_formulas", "range.format", "workbook.save")


def _request(state):
    if getattr(state, "domain", None) != "libreoffice_calc" or re.search(
        r"\b(?:compound|compounding|effective|continuous|cumulative|discount|annuity|round)\b",
        state.instruction, re.I,
    ):
        return None
    spec = requested_period_rate_column(state.instruction)
    if not spec or not re.search(r"%|\bpercent", spec["header"], re.I):
        return None
    return spec


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _format_type(cell):
    details = cell.get("number_formats")
    kind = details.get("type") if isinstance(details, dict) else None
    return kind & ~1 if isinstance(kind, int) and not isinstance(kind, bool) else None


def _source(state, events):
    if not (spec := _request(state)):
        return None
    inspections = [p for _, a, _, p in events if a == "workbook.inspect"]
    if not inspections:
        return None
    original = {s.get("name"): _used_rectangle(s) for s in inspections[0].get("sheets", [])}
    candidates = {}
    for event, action, args, payload in events:
        if action != "range.read" or not _same_document(events, event, payload):
            continue
        sheet, area = args.get("sheet"), rectangle(args.get("range"))
        if (not area or area != original.get(sheet) or (sheet, area) in candidates
                or payload.get("sheet", sheet) != sheet
                or rectangle(payload.get("range", args.get("range"))) != area):
            continue
        rows = _complete_rows(payload, area)
        if not rows or len(rows) < 2:
            continue
        headers = rows[0]
        annual = [i for i, h in enumerate(headers) if _alias(h) in {
            "annual rate", "yearly rate", "annual rate percent", "yearly rate percent",
        } and re.search(r"%|\bpercent", str(h), re.I)]
        periods = [i for i, h in enumerate(headers) if _alias(h) == "period per year"]
        if (len(annual) != 1 or len(periods) != 1
                or any(_alias(h) == _alias(spec["header"]) for h in headers)):
            continue
        columns = [area[0] + annual[0], area[0] + periods[0]]
        if any(e.step < event.step and a != "sheet.create"
               and any(_source_touched(a, ar, sheet, c, area[1], area[3]) for c in columns)
               for e, a, ar, _ in events):
            continue
        observed = _cells([(event, action, args, payload)])
        data = []
        for row in range(area[1] + 1, area[3] + 1):
            rate = observed.get((sheet, columns[0], row), [{}])[-1]
            count = observed.get((sheet, columns[1], row), [{}])[-1]
            kind = _format_type(rate)
            if (rate.get("kinds") not in {"number", "formula"}
                    or count.get("kinds") not in {"number", "formula"}
                    or not _number(rate.get("values")) or not _number(count.get("values"))
                    or count["values"] <= 0 or kind not in {4, 16, 32, 64}
                    or _format_type(count) not in {16, 32, 64}):
                break
            data.append({"row": row, "rate": rate["values"], "count": count["values"],
                         "factor": 100 if kind == 4 else 1, "source_format_type": kind})
        if len(data) != area[3] - area[1]:
            continue
        candidates[(sheet, area)] = {"sheet": sheet, "area": area, "columns": columns,
                                      "headers": [headers[annual[0]], headers[periods[0]]],
                                      "step": event.step, "data": data, "output_header": spec["header"]}
    return next(iter(candidates.values())) if len(candidates) == 1 else None


def outcome_issues(state):
    events = _events(state) if _request(state) else []
    source = _source(state, events)
    if source is None:
        return []  # Ambiguous sources/units stay with existing model review.
    changes = [(e, a, args) for e, a, args, _ in events
               if not action_is_read_only(a) and not action_is_save(a)]
    if not changes:
        return []
    cells = _cells(events)
    sheet, columns, area = source["sheet"], source["columns"], source["area"]
    target = {"sheet": sheet, "header": source["output_header"], "source_headers": source["headers"]}

    def issue(code, expected, observed, mismatch=False):
        return _issue("period_rate." + code, target, expected, observed, actions=ACTIONS, mismatch=mismatch)

    missing, changed = [], []
    for item in source["data"]:
        for column, expected in zip(columns, (item["rate"], item["count"])):
            cell = cells.get((sheet, column, item["row"]), [{}])[-1]
            touched = max((e.step for e, a, ar in changes if a != "sheet.create"
                           and _source_touched(a, ar, sheet, column, item["row"], item["row"])), default=0)
            address = f"{_column(column)}{item['row']}"
            if cell.get("step", 0) <= touched or cell.get("kinds") not in {"number", "formula"}:
                missing.append(address)
            elif cell.get("values") != expected:
                changed.append(address)
    if missing or changed:
        return [issue("source_unverified" if missing else "source_changed",
                      "current source inputs retain their original observed numeric values",
                      {"unverified_cells": missing, "changed_cells": changed}, bool(changed))]
    after = max([e.step for e, _, _ in changes] + [e.step for e, a, _, _ in events if action_is_save(a)])
    headers = [key for key, observed in cells.items()
               if key[0] == sheet and _alias(observed[-1].get("values")) == _alias(source["output_header"])]
    if len(headers) != 1 or headers[0][2] != area[1] or area[0] <= headers[0][1] <= area[2]:
        return [issue("output_unverified", "read the uniquely named new output column and its complete numeric rows", None)]
    output_column = headers[0][1]
    missing, wrong = [], []
    for item in source["data"]:
        address = f"{_column(output_column)}{item['row']}"
        cell = cells.get((sheet, output_column, item["row"]), [{}])[-1]
        if cell.get("action") != "range.read" or cell.get("step", 0) <= after:
            missing.append(address)
            continue
        value = cell.get("values")
        expected = item["rate"] * item["factor"] / item["count"]
        if (cell.get("kinds") not in {"number", "formula"} or not _number(value)
                or _format_type(cell) not in {16, 32, 64}
                or not math.isclose(value, expected, rel_tol=1e-10, abs_tol=1e-9)):
            wrong.append({"cell": address, "observed": value, "source_format_type": item["source_format_type"]})
    if missing or wrong:
        return [issue("output_unverified" if missing else "unit_mismatch",
                      "per-period rates in percentage-point numbers; divide annual percentage points by periods per year, converting stored fractions only when the source uses percent number formatting",
                      {"unverified_cells": missing, "incorrect_cells": wrong}, bool(wrong))]
    return []


def constrain_tool(function, state):
    if function.get("name") not in {"adapter__range_write", "adapter__cells_set_formulas", "adapter__range_read", "propose_done"}:
        return
    source = _source(state, _events(state)) if _request(state) else None
    if source is None:
        return
    types = sorted({item["source_format_type"] for item in source["data"]})
    function["description"] += (
        f" Observed rate-unit evidence: source headers {source['headers']!r}; annual native number-format types {types!r}. "
        "An annual percent-labelled column with ordinary NUMBER/SCIENTIFIC/FRACTION formatting already stores percentage points; "
        "dividing by a dimensionless period count preserves those units. Only native PERCENT formatting stores a fraction "
        "that needs conversion to percentage points for a plain-number result. Check the entire output column against "
        "the observed input units; formatting cannot correct an extra factor of 100. Keep original inputs unchanged. "
        "Choose your own equivalent expressions and corrections."
    )
