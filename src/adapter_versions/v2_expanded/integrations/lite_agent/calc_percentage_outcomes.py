"""Category frequency pivots: bind measures and verify saved cell contents.

This deliberately recognizes independent, explicitly named category percentages,
not weighted shares or cross-tabs. Inputs come from public instructions and live
source cells; no task IDs, reference workbooks or expected answers are used.
"""
from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any

from .completion_outcomes import (
    _alias, _complete_rows, _complete_source_range, _definition, _issue,
    _same_document, rectangle,
)
from .completion_policy import action_is_read_only, action_is_save


ACTIONS = ("workbook.inspect", "range.read", "pivot.create", "range.format", "workbook.save")


def request(instruction: str, count: int) -> dict | None:
    """Only named independent category frequencies, with no other measure."""
    if not count or re.search(
        r"\b(?:weighted|sum|revenue|sales|cross.?tab|versus|against)\b", instruction, re.I
    ):
        return None
    match = re.search(
        r"\bpercentages?(?:\s+distributions?)?\s+(?:of|for)\s+(.+?)(?:[.!?;]|$)",
        instruction, re.I,
    )
    if not match:
        return None
    phrase = re.split(r"\s+(?:in|on|stacked|separated)\s+", match[1], maxsplit=1, flags=re.I)[0]
    phrase = re.sub(r",\s+and\s+", ", ", phrase, flags=re.I)
    groups = [g.strip(" \"'") for g in re.split(r"\s*,\s*|\s+and\s+", phrase, flags=re.I) if g.strip()]
    if len(groups) != count or len(set(map(_alias, groups))) != count:
        return None
    return {"groups": groups}


def source_observation(events: list, spec: dict) -> dict | None:
    for event, action, args, payload in reversed(events):
        if action != "range.read" or not _same_document(events, event, payload):
            continue
        sheet, area = args.get("sheet"), args.get("range")
        rect = rectangle(area)
        rows = _complete_rows(payload, rect)
        if (not rows or len(rows) < 2 or payload.get("sheet", sheet) != sheet
                or rectangle(payload.get("range", area)) != rect
                or not _complete_source_range(events, sheet, rect)):
            continue
        headers = rows[0]
        groups = []
        for name in spec["groups"]:
            hits = [h for h in headers if _alias(h) == _alias(name)]
            if len(hits) != 1:
                break
            groups.append(hits[0])
        if len(groups) != len(spec["groups"]):
            continue
        if any(e.step > event.step and not action_is_read_only(a) and not action_is_save(a)
               and (a == "gui" or ar.get("sheet") == sheet or ar.get("destination_sheet") == sheet)
               for e, a, ar, _ in events):
            continue
        counts = {}
        try:
            for group in groups:
                column = headers.index(group)
                values = Counter()
                for index, row in enumerate(rows[1:], 1):
                    kind = payload["kinds"][index][column]
                    value = payload["values"][index][column]
                    if kind not in {"string", "number", "formula", "blank"}:
                        raise ValueError("unobserved category cell type")
                    if kind in {"number", "formula"} and (isinstance(value, bool) or not math.isfinite(float(value))):
                        raise ValueError("invalid category cell")
                    if kind == "formula" and str(row[column]).startswith("#"):
                        raise ValueError("source category formula error")
                    # COUNT counts nonempty values, not a different ID column.
                    # Empty categories have no nonempty values to count.
                    label = str(row[column])
                    if not label.strip():
                        continue
                    values[label] += int(kind != "blank" and value not in (None, ""))
                if not sum(values.values()):
                    raise ValueError("no nonempty category values")
                counts[group] = dict(values)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        return {"sheet": sheet, "range": area, "groups": groups, "counts": counts, "step": event.step}
    return None


def valid_definition(pivot: dict, group: str, source: dict) -> bool:
    fields = pivot.get("data_fields")
    return bool(
        pivot.get("source_sheet") == source["sheet"]
        and rectangle(pivot.get("source_range")) == rectangle(source["range"])
        and pivot.get("row_fields") == [group]
        and pivot.get("column_fields") == [] and pivot.get("page_fields") == []
        and isinstance(fields, list) and len(fields) == 1
        and fields[0].get("field") == group
        and str(fields[0].get("aggregation", "")).lower() == "count"
        # UNO also returns the numeric DataPilotFieldReferenceType constant.
        and str(fields[0].get("show_data_as", "")).lower() in {
            "total_percentage", "7", "column_percentage", "6",
        }
    )


def _cell(cells: dict, sheet: str, column: int, row: int, after: int) -> dict | None:
    found = cells.get((sheet, column, row), [])
    if found and found[-1]["step"] > after and found[-1]["action"] == "range.read":
        return found[-1]
    return None


def _percentage(cell: dict, expected: float) -> bool:
    if cell.get("kinds") not in {"number", "formula"} or isinstance(cell.get("values"), bool):
        return False
    try:
        native = float(cell["values"])
        if not math.isfinite(native) or not math.isclose(native, expected, rel_tol=1e-9, abs_tol=1e-10):
            return False
        # Check the full display token, including the percent sign. Tolerance
        # follows its visible decimal precision, not a fixed loose epsilon.
        text = cell["display"].replace("\N{NO-BREAK SPACE}", " ").strip()
        match = re.fullmatch(r"([+-]?\d+)(?:([.,])(\d+))?\s*%", text)
        if not match:
            return False
        places = len(match[3] or "")
        shown = float(text.rstrip("% ").replace(",", ".")) / 100
        return abs(shown - expected) <= 0.5 * 10 ** (-places - 2) + 1e-12
    except (KeyError, TypeError, ValueError):
        return False


def output_issue(cells: dict, sheet: str, pivot: dict, group: str, counts: dict, after: int) -> dict | None:
    target = {"sheet": sheet, "name": pivot.get("name"), "range": pivot.get("output_range")}
    rect = rectangle(pivot.get("output_range"))
    expected = {"headers": [group, "Count - " + group],
                "percentages": {key: n / sum(counts.values()) for key, n in counts.items()}, "grand_total": 1}
    if not rect:
        return _issue("pivot.output_unverified", target, expected, None, actions=ACTIONS)
    grid = [[_cell(cells, sheet, c, r, after) for c in range(rect[0], rect[2] + 1)]
            for r in range(rect[1], rect[3] + 1)]
    if any(cell is None for row in grid for cell in row):
        return _issue("pivot.output_unverified", target,
                      {**expected, "evidence": "read every output cell after final mutation and save"},
                      None, actions=ACTIONS)
    problems = []
    if rect[2] - rect[0] != 1 or len(grid) != len(counts) + 2:
        problems.append("expected two columns, one row per source category, and one grand total")
    else:
        headers = [c["display"] for c in grid[0]]
        if (headers != expected["headers"] or [c.get("values") for c in grid[0]] != expected["headers"]
                or any(c.get("kinds") != "string" for c in grid[0])):
            problems.append({"headers": headers, "expected": expected["headers"]})
        observed = {}
        for label, value in grid[1:-1]:
            key = label["display"]
            if (key not in counts or key in observed or label.get("kinds") != "string"
                    or label.get("values") != key):
                problems.append({"unexpected_or_duplicate_category": key})
            else:
                observed[key] = value
                if not _percentage(value, expected["percentages"][key]):
                    problems.append({"category": key, "expected": expected["percentages"][key], "cell": value})
        if missing := sorted(counts.keys() - observed.keys()):
            problems.append({"missing_categories": missing})
        label, value = grid[-1]
        if (label["display"].casefold() not in {"total result", "grand total", "total"}
                or label.get("kinds") != "string" or label.get("values") != label["display"]
                or not _percentage(value, 1)):
            problems.append({"invalid_grand_total": [label, value]})
    if problems:
        return _issue("pivot.output_mismatch", target, expected, problems, actions=ACTIONS,
                      step=max(c["step"] for row in grid for c in row), mismatch=True)
    return None


def outcome_issues(state: Any, events: list, spec: dict, objects: list, after: int, inventory_step: int) -> list:
    from .calc_scaled_outcomes import _cells

    source = source_observation(events, spec)
    if source is None:
        return [_issue("pivot.source_unverified", spec,
                       "read the complete native source extent, including headers, cell types and values",
                       [{"sheet": p.get("source_sheet"), "range": p.get("source_range")} for _, p in objects],
                       actions=ACTIONS)]
    issues = []
    cells = _cells(events)
    for sheet, pivot in objects:
        if not any(valid_definition(pivot, g, source) for g in source["groups"]):
            unknown = any(pivot.get(k) is None for k in _definition(pivot)) or pivot.get("inspect_error")
            issues.append(_issue("pivot.definition_unverified" if unknown else "pivot.definition_mismatch",
                                 {"sheet": sheet, "name": pivot.get("name"), "range": pivot.get("output_range")},
                                 {"independent_groupings": source["groups"], "measure": "same category as row field",
                                  "aggregation": "count", "show_data_as": "total_percentage",
                                  "source_sheet": source["sheet"], "source_range": source["range"]},
                                 _definition(pivot), actions=ACTIONS, step=inventory_step, mismatch=not unknown))
    for group in source["groups"]:
        matches = [(s, p) for s, p in objects if p.get("row_fields") == [group]]
        if len(matches) != 1:
            issues.append(_issue("pivot.grouping_missing_or_duplicate", {"group": group},
                                 "one independent category percentage pivot", [p.get("name") for _, p in matches],
                                 actions=ACTIONS, step=inventory_step, mismatch=True))
        else:
            sheet, pivot = matches[0]
            issue = output_issue(cells, sheet, pivot, group, source["counts"][group], after)
            if issue:
                issues.append(issue)
    if re.search(r"\bstacked\b", state.instruction, re.I):
        ordered = [(s, p, rectangle(p.get("output_range"))) for s, p in objects]
        ordered = sorted((item for item in ordered if item[2]), key=lambda item: (item[0], item[2][1]))
        for (sheet, _, left), (other_sheet, _, right) in zip(ordered, ordered[1:]):
            blank = bool(re.search(r"\bblank\s+(?:line|row)", state.instruction, re.I))
            if sheet != other_sheet or left[0] != right[0] or right[1] <= left[3] + int(blank):
                issues.append(_issue("pivot.layout_mismatch", sheet, "stacked disjoint outputs with requested blank row",
                                     [left, right], actions=ACTIONS, step=inventory_step, mismatch=True))
            elif blank:
                gap = [_cell(cells, sheet, c, r, after)
                       for r in range(left[3] + 1, right[1]) for c in range(left[0], max(left[2], right[2]) + 1)]
                if any(cell is None for cell in gap):
                    issues.append(_issue("pivot.gap_unverified", {"sheet": sheet, "rows": [left[3] + 1, right[1] - 1]},
                                         "read blank separator cells after save", None, actions=ACTIONS))
                elif any(cell["display"] or cell.get("kinds") != "blank" or cell.get("values") is not None for cell in gap):
                    issues.append(_issue("pivot.gap_mismatch", sheet, "blank separator cells", gap,
                                         actions=ACTIONS, step=max(c["step"] for c in gap), mismatch=True))
    return issues


def constrain_tool(function: dict, state: Any) -> None:
    from .completion_outcomes import _events
    from .instruction_semantics import requested_pivot_count
    from .tool_catalog import build_tools

    if getattr(state, "domain", None) != "libreoffice_calc":
        return
    spec = request(state.instruction, requested_pivot_count(state.instruction))
    if spec is None:
        return
    name = function.get("name")
    if name == "adapter__adapter_call":
        parameters = function.get("parameters", {})
        routes = parameters.get("x-allowed-routes", [])
        pairs = {(r.get("adapter"), r.get("action")) for r in routes if isinstance(r, dict)}
        if pairs == {("libreoffice_calc", "pivot.create")}:
            direct = build_tools("libreoffice_calc", ["pivot.create"], include_gui=False,
                                 include_control_tools=False, strict_generic=True)[0]["function"]
            constrain_tool(direct, state)
            payload = parameters.get("properties", {}).get("payload", {})
            payload.setdefault("properties", {})["params"] = direct["parameters"]
            function["description"] += " " + direct["description"]
        return
    if name == "adapter__pivot_create":
        function["description"] += (
            " This request is for category frequencies: use the exact observed category header "
            "in BOTH row_fields and data_fields.field, aggregation=count, show_data_as=total_percentage. "
            "Do not substitute an ID/respondent column: COUNT accepts category text and a different "
            "measure produces a different header. Native output must retain Count - <category>."
        )
        source = source_observation(_events(state), spec)
        if source:
            function["parameters"]["oneOf"] = [{"properties": {
                "row_fields": {"const": [group]},
                "data_fields": {"type": "array", "minItems": 1, "maxItems": 1, "items": {
                    "properties": {"field": {"const": group}, "aggregation": {"const": "count"},
                                   "show_data_as": {"enum": ["total_percentage", "column_percentage"]}},
                    "required": ["field", "aggregation", "show_data_as"],
                }},
            }, "required": ["row_fields", "data_fields"]} for group in source["groups"]]
    elif name == "adapter__range_read":
        function["description"] += (
            " Category percentage completion requires full source rows and, after final save, "
            "all pivot output cells including exact headers, numeric values, displayed percentages, "
            "grand totals and blank separators. Reading only the title cannot verify these tables."
        )
