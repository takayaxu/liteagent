"""Conservative period-change completion checks from native cell/chart evidence.

The model owns formulas, destinations and repair order. Unsupported or ambiguous
instructions/layouts are left to existing review; no task identity is consumed.
"""
from __future__ import annotations

import math
import re

from .completion_outcomes import _events, _issue, _used_rectangle, rectangle
from .completion_policy import action_is_read_only, action_is_save
from .calc_formula_contract import _column, _observe, numeric

ACTIONS = ("range.read", "workbook.inspect", "range.write", "cells.set_formulas",
           "range.clear", "range.format", "chart.create", "workbook.save")
MONTHS = ("january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december")


def _label(value):
    return " ".join(str(value).strip().casefold().split())


def _period(value, unit):
    value = _label(value).rstrip(".")
    if unit == "month":
        hits = [i for i, name in enumerate(MONTHS) if value in {name, name[:3]}]
        return hits[0] if len(hits) == 1 else None
    match = re.fullmatch(r"(?:q|quarter\s*)([1-4])", value)
    return int(match[1]) - 1 if match else None


def request(instruction):
    change = re.search(r"\b(month|quarter)[ -]on[ -]\1\s+(?:growth|change)\s+(?:percentage|percent)\b",
                       instruction, re.I)
    if not change or re.search(r"\b(?:year.on.year|compound|cumulative|moving|rolling)\b", instruction, re.I):
        return None
    # Two explicitly named output rows, with the sum requested before the change.
    rows = list(re.finditer(r"\brow\s+(?:called|named)\s+[\"']([^\"']+)[\"']", instruction, re.I))
    if len(rows) != 2 or rows[0].start() > change.start() or rows[1].start() < change.start():
        return None
    if not re.search(r"\b(?:total|sum)\b", instruction[:rows[0].start()], re.I):
        return None
    span = re.search(r"\bfor\s+([A-Za-z]+\s*[1-4]?)\s+(?:to|through)\s+([A-Za-z]+\s*[1-4]?)\b",
                     instruction[change.end():], re.I)
    if not span:
        return None
    unit = change[1].lower()
    start, end = (_period(span[i], unit) for i in (1, 2))
    if start is None or end is None or start > end:
        return None
    names = [m[1] for m in rows]
    if _label(names[0]) == _label(names[1]):
        return None
    charts = bool(re.search(r"\bbars?\b", instruction[rows[0].end():change.start()], re.I)
                  and re.search(r"\bline\s+chart\b", instruction[rows[1].end():], re.I)
                  and re.search(r"\bchart\s+titles?\b", instruction, re.I)
                  and re.search(r"\brow\s+headers?\b", instruction, re.I))
    return {"unit": unit, "start": start, "end": end, "names": names, "charts": charts}


def _source(events, spec):
    candidates = []
    for event, action, args, payload in events:
        if action != "range.read":
            continue
        before = [(e, p) for e, a, _, p in events if a == "workbook.inspect" and e.step < event.step]
        if not before:
            continue
        snapshot = before[-1][1]
        sheet = args.get("sheet")
        info = next((s for s in snapshot.get("sheets", []) if s.get("name") == sheet), {})
        rect = rectangle(args.get("range"))
        if not rect or rect != _used_rectangle(info):
            continue
        # Only an unmodified source establishes the detail extent and identity.
        if any(e.step < event.step and not action_is_read_only(a) and not action_is_save(a)
               and a not in {"workbook.open", "workbook.create_new"} for e, a, _, _ in events):
            continue
        grids = {}
        _observe(grids, event, args, snapshot.get("url"))
        grid = grids.get(sheet, {})
        if not grid:
            continue
        header = rect[1]
        periods = [(c, _period(grid.get((c, header), {}).get("value"), spec["unit"]))
                   for c in range(rect[0], rect[2] + 1)]
        periods = [(c, p) for c, p in periods if p is not None]
        if len(periods) < 2 or any(c2 != c1 + 1 or p2 != p1 + 1
                                  for (c1, p1), (c2, p2) in zip(periods, periods[1:])):
            continue
        if periods[0][0] <= rect[0] or not all(p in dict((p, c) for c, p in periods)
                                                     for p in range(spec["start"] - 1, spec["end"] + 1)):
            continue
        details = [(c, r) for c, _ in periods for r in range(header + 1, rect[3] + 1)]
        if not details or not all(numeric(grid.get(k, {}).get("value")) for k in details):
            continue
        candidates.append({"sheet": sheet, "rect": rect, "header": header, "periods": periods,
                           "grid": grid, "details": details})
    identities = {(s["sheet"], s["rect"]) for s in candidates}
    return candidates[0] if len(identities) == 1 else None


def _live_cells(events):
    grids = {}
    last_save = 0
    documents = [p.get("url") for _, a, _, p in events if a == "workbook.inspect" and p.get("url")]
    document = documents[-1] if documents else None
    for event, action, args, payload in events:
        if action_is_save(action):
            last_save = event.step
        elif action == "range.read":
            _observe(grids, event, args, document)
        elif not action_is_read_only(action) and action.removeprefix("uncertain:") not in {"chart.create", "sheet.create"}:
            # Native cell values become unknown after an uncertain change. Formula
            # results anywhere may depend on an edited cell, so invalidate them too.
            rect = rectangle(args.get("range"))
            writes = [rectangle(w.get("cell")) for w in args.get("writes", [])]
            areas = [r for r in [rect, *writes] if r]
            for sheet, grid in grids.items():
                for (c, r), cell in grid.items():
                    touched = (sheet == args.get("sheet") and areas
                               and any(a <= c <= x and b <= r <= y for a, b, x, y in areas))
                    unknown = not areas and action not in {"workbook.open", "workbook.create_new"}
                    if touched or unknown or cell.get("kind") == "formula":
                        cell["native"] = False
            if action == "range.write":
                _observe(grids, event, args, document)
    return grids, last_save


def _range_cells(value, default_sheet):
    # Native UNO A1 source representation, including quoted sheet names.
    match = re.fullmatch(r"(?:\$?(?:'((?:[^']|'')+)'|([^.!]+))[.!])?(.+)", str(value))
    if not match:
        return None
    sheet = (match[1] or match[2] or default_sheet).replace("''", "'")
    rect = rectangle(match[3])
    if not rect or (rect[2] - rect[0] + 1) * (rect[3] - rect[1] + 1) > 512:
        return None
    return [(sheet, c, r) for r in range(rect[1], rect[3] + 1) for c in range(rect[0], rect[2] + 1)]


def _chart_issues(events, source, spec, output_rows):
    after = max(e.step for e, a, _, _ in events if not action_is_read_only(a))
    snapshots = [(e, p) for e, a, _, p in events if a == "workbook.inspect" and e.step > after]
    if not snapshots:
        return [_issue("period.charts_unverified", source["sheet"], "native inventory after changes and save",
                       None, actions=ACTIONS)]
    event, snapshot = snapshots[-1]
    sheets = snapshot.get("sheets", [])
    if (snapshot.get("context_truncated") or snapshot.get("sheets_omitted_from_context")
            or any(not isinstance(s.get("charts"), list) or s.get("charts_inspect_error")
                   or s.get("charts_omitted_from_context") for s in sheets)):
        return [_issue("period.charts_unverified", source["sheet"], "complete native chart inventory",
                       None, actions=ACTIONS, step=event.step)]
    issues = []
    for index, name in enumerate(spec["names"]):
        charts = [chart for s in sheets for chart in s.get("charts", []) if _label(chart.get("title")) == _label(name)]
        columns = [c for c, p in source["periods"] if index == 0 or spec["start"] <= p <= spec["end"]]
        expected = {"title": name, "type": "bar" if index == 0 else "line",
                    "categories": [source["grid"][(c, source["header"])]["value"] for c in columns],
                    "value_cells": [f"{source['sheet']}.{_column(c)}{output_rows[index]}" for c in columns]}
        if len(charts) != 1:
            issues.append(_issue("period.chart_mismatch", name, expected, charts, actions=ACTIONS,
                                 step=event.step, mismatch=True))
            continue
        chart = charts[0]
        series, axes = chart.get("data_series"), chart.get("category_axes")
        if (not isinstance(series, list) or not isinstance(axes, list)
                or chart.get("data_series_inspect_error") or chart.get("type") is None):
            issues.append(_issue("period.chart_unverified", name, expected, chart,
                                 actions=ACTIONS, step=event.step))
            continue
        cells = []
        complete = True
        for item in series:
            ranges = item.get("source_ranges")
            if not isinstance(ranges, list) or not ranges:
                complete = False
                continue
            for area in ranges:
                parsed = _range_cells(area, chart.get("source_sheet", source["sheet"]))
                if parsed is None:
                    complete = False
                else:
                    cells.extend(parsed)
        wanted = [(source["sheet"], c, output_rows[index]) for c in columns]
        labels = axes[0].get("labels") if len(axes) == 1 else None
        mismatch = chart.get("type") != expected["type"] or len(series) != 1 or cells != wanted or labels != expected["categories"]
        if not complete or labels is None or mismatch:
            issues.append(_issue("period.chart_mismatch" if complete and labels is not None else "period.chart_unverified",
                                 {"title": name, "name": chart.get("name")}, expected,
                                 {"type": chart.get("type"), "series": series, "categories": labels},
                                 actions=ACTIONS, step=event.step, mismatch=complete and labels is not None))
    return issues


def outcome_issues(state):
    if state.domain != "libreoffice_calc" or not (spec := request(state.instruction)):
        return []
    events = _events(state)
    if not any(not action_is_read_only(a) and not action_is_save(a) for _, a, _, _ in events):
        return []
    source = _source(events, spec)
    if source is None:
        return []  # Ambiguous/unsupported layout: existing completion review owns it.
    grids, last_save = _live_cells(events)
    grid = grids.get(source["sheet"], {})
    missing, wrong = [], []
    for key in source["details"]:
        observed = grid.get(key, {})
        if not observed.get("native"):
            missing.append(f"{_column(key[0])}{key[1]}")
        elif observed.get("value") != source["grid"][key]["value"]:
            wrong.append({"cell": f"{_column(key[0])}{key[1]}", "expected": source["grid"][key]["value"],
                          "observed": observed.get("value")})
    rows = []
    for name in spec["names"]:
        hits = [(c, r) for (c, r), cell in grid.items() if _label(cell.get("value")) == _label(name)
                and c < source["periods"][0][0] and r > source["rect"][3]]
        if len(hits) != 1:
            missing.append({"row_label": name, "sheet": source["sheet"], "observed_matches": hits})
            rows.append(None)
        else:
            c, r = hits[0]
            rows.append(r)
            if not grid[(c, r)].get("native") or grid[(c, r)]["step"] <= last_save:
                missing.append(f"{_column(c)}{r}")
    totals = {c: sum(source["grid"][(c, r)]["value"] for r in range(source["header"] + 1, source["rect"][3] + 1))
              for c, _ in source["periods"]}
    if any(not totals[source["periods"][ci - 1][0]]
           for ci, (_, period) in enumerate(source["periods"])
           if ci and spec["start"] <= period <= spec["end"]):
        return []  # Zero-base growth needs an explicit user policy.
    for index, row in enumerate(rows):
        if row is None:
            continue
        for ci, (c, period) in enumerate(source["periods"]):
            if index == 0:
                expected = totals[c]
            elif spec["start"] <= period <= spec["end"] and ci and totals[source["periods"][ci - 1][0]]:
                previous = totals[source["periods"][ci - 1][0]]
                expected = (totals[c] - previous) / previous
            else:
                expected = None
            cell = grid.get((c, row), {})
            address = f"{_column(c)}{row}"
            if not cell.get("native") or cell.get("step", 0) <= last_save:
                missing.append(address)
                continue
            value = cell.get("value")
            if (expected is None and value not in (None, "")) or (expected is not None and
                    (not numeric(value) or not math.isclose(value, expected, rel_tol=1e-7, abs_tol=1e-9))):
                wrong.append({"cell": address, "period": source["grid"][(c, source["header"])]["value"],
                              "row_label": spec["names"][index], "expected": expected, "observed": value})
    issues = []
    if missing:
        issues.append(_issue("period.cells_unverified", {"sheet": source["sheet"], "cells_or_labels": missing[:32]},
                             "native range.read of source and both labelled output rows after final save",
                             {"unverified_count": len(missing)}, actions=ACTIONS))
    if wrong:
        issues.append(_issue("period.values_mismatch", source["sheet"], "sum detail rows; align each fractional change to its current period; preserve source",
                             wrong[:32], actions=ACTIONS, mismatch=True))
    if spec["charts"] and all(r is not None for r in rows):
        issues.extend(_chart_issues(events, source, spec, rows))
    return issues
