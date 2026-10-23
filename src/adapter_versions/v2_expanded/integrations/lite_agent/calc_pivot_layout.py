"""Instruction-derived pivot spacing, checked against live rectangles and cells."""
from __future__ import annotations

import re
from typing import Any

from .completion_outcomes import _events, _issue, rectangle
from .completion_policy import action_is_read_only, action_is_save
from .instruction_semantics import NUMBER_WORDS


ACTIONS = ("workbook.inspect", "range.read", "pivot.create", "workbook.save")


def spacing_requirement(instruction: str) -> dict | None:
    if not re.search(r"\bstack(?:ed)?\b|\bone\s+(?:below|under)\s+(?:the\s+)?other\b", instruction, re.I):
        return None
    words = "|".join(NUMBER_WORDS)
    clauses = re.split(r"[.!?;]", instruction)
    spacing_text = " ".join(clause for clause in clauses if re.search(
        r"\bstack(?:ed)?\b|\bseparat(?:e|ed)\b|\bbetween\b", clause, re.I
    ))
    match = re.search(
        rf"\b(?:(at\s+least|at\s+most|exactly)\s+)?(an?|{words}|\d+)\s+blank\s+(?:rows?|lines?)\b",
        spacing_text, re.I,
    )
    if match:
        token = match[2].casefold()
        count = int(token) if token.isdigit() else NUMBER_WORDS.get(token, 1)
        qualifier = re.sub(r"\s+", " ", (match[1] or "").casefold())
        return {"blank_rows": count, "relation": {"at least": "minimum", "at most": "maximum"}.get(qualifier, "exact")}
    if re.search(r"\bno\s+blank\s+(?:rows?|lines?)\b|\badjacent\b", spacing_text, re.I):
        return {"blank_rows": 0, "relation": "exact"}
    # An unspecified plural does not imply an exact count.
    if re.search(r"\bblank\s+(?:rows?|lines?)\b", spacing_text, re.I):
        return {"blank_rows": 1, "relation": "minimum"}
    return {"blank_rows": 0, "relation": "minimum"}


def _gap_matches(gap: int, requirement: dict) -> bool:
    count = requirement["blank_rows"]
    return gap >= 0 and {"exact": gap == count, "minimum": gap >= count, "maximum": gap <= count}[requirement["relation"]]


def _column(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def layout_issues(state: Any, events: list, objects: list, after: int, inventory_step: int) -> list:
    from .calc_scaled_outcomes import _cells

    requirement = spacing_requirement(state.instruction)
    if requirement is None:
        return []
    issues = []
    ordered = []
    for sheet, pivot in objects:
        rect = rectangle(pivot.get("output_range"))
        if rect is None:
            issues.append(_issue("pivot.layout_unverified", {"sheet": sheet, "name": pivot.get("name")},
                                 "native occupied output_range", pivot.get("output_range"), actions=ACTIONS))
        else:
            ordered.append((sheet, pivot, rect))
    if issues:
        return issues
    ordered.sort(key=lambda item: (item[0], item[2][1]))
    cells = _cells(events)

    def cell_at(sheet: str, column: int, row: int) -> dict | None:
        observations = cells.get((sheet, column, row), [])
        if observations and observations[-1]["step"] > after and observations[-1]["action"] == "range.read":
            return observations[-1]
        return None

    for (sheet, previous, left), (other_sheet, pivot, right) in zip(ordered, ordered[1:]):
        gap = right[1] - left[3] - 1
        target = {"sheet": other_sheet, "name": pivot.get("name"), "range": pivot.get("output_range")}
        expected = {**requirement, "sheet": sheet, "below_range": previous["output_range"],
                    "left_column": _column(left[0])}
        if requirement["relation"] == "exact":
            expected["destination"] = f"{_column(left[0])}{left[3] + requirement['blank_rows'] + 1}"
        if sheet != other_sheet or left[0] != right[0] or not _gap_matches(gap, requirement):
            issues.append(_issue("pivot.layout_mismatch", target, expected,
                                 {"blank_rows": gap, "previous_range": previous["output_range"],
                                  "output_range": pivot["output_range"]},
                                 actions=ACTIONS, step=inventory_step, mismatch=True))
            continue
        gap_cells = [cell_at(sheet, c, r) for r in range(left[3] + 1, right[1])
                     for c in range(left[0], max(left[2], right[2]) + 1)]
        if any(cell is None for cell in gap_cells):
            issues.append(_issue("pivot.gap_unverified", {**target, "rows": [left[3] + 1, right[1] - 1]},
                                 "read every separator cell after final mutation and save", None, actions=ACTIONS))
        elif any(c["display"] or c.get("kinds") != "blank" or c.get("values") is not None for c in gap_cells):
            issues.append(_issue("pivot.gap_mismatch", target, "native blank separator cells", gap_cells,
                                 actions=ACTIONS, step=max(c["step"] for c in gap_cells), mismatch=True))
    return issues


def _observed_areas(state: Any) -> dict[str, set[str]]:
    objects = {}
    for _, action, args, payload in _events(state):
        if action == "workbook.inspect" and isinstance(payload.get("sheets"), list):
            objects = {(s["name"], p.get("name")): p["output_range"] for s in payload["sheets"]
                       if s.get("name") for p in s.get("pivot_tables", [])
                       if rectangle(p.get("output_range"))}
        elif action == "pivot.create" and rectangle(payload.get("output_range")):
            sheet = payload.get("destination_sheet", args.get("destination_sheet"))
            if sheet:
                objects[sheet, args.get("name")] = payload["output_range"]
        elif not action_is_read_only(action) and not action_is_save(action):
            # Edits can shift live rectangles. Reobserve before binding a gap
            # to an old range, especially after an uncertain replacement.
            objects.clear()
    areas: dict[str, set[str]] = {}
    for (sheet, _), area in objects.items():
        areas.setdefault(sheet, set()).add(area)
    return areas


def constrain_tool(function: dict, state: Any) -> None:
    if getattr(state, "domain", None) != "libreoffice_calc":
        return
    requirement = spacing_requirement(state.instruction)
    if requirement is None:
        return
    name = function.get("name")
    parameters = function.get("parameters", {})
    if name == "adapter__adapter_call":
        routes = parameters.get("x-allowed-routes", [])
        if {(r.get("adapter"), r.get("action")) for r in routes if isinstance(r, dict)} != {("libreoffice_calc", "pivot.create")}:
            return
        parameters = parameters.get("properties", {}).get("payload", {}).get("properties", {}).get("params", {})
    elif name != "adapter__pivot_create":
        return
    properties = parameters.get("properties", {})
    if "below_range" not in properties:
        return
    # Qwen's XML/native parser may stringify a string-or-object union. Keep
    # A1 positions as strings and expose relative fields with scalar types.
    destination = properties.get("destination", {})
    if "oneOf" in destination:
        absolute = next(branch for branch in destination["oneOf"] if branch.get("type") == "string")
        properties["destination"] = {**absolute, "description": "One absolute A1 anchor. For relative placement omit this and pass top-level below_range and blank_rows."}
    areas = _observed_areas(state)
    observed_ranges = sorted({area for ranges in areas.values() for area in ranges})
    if observed_ranges:
        properties["below_range"]["description"] += " Observed pivot rectangles: " + ", ".join(observed_ranges) + "."
        gap_schema = {"type": "integer", "minimum": 0}
        if requirement["relation"] == "exact":
            gap_schema["const"] = requirement["blank_rows"]
        else:
            gap_schema[requirement["relation"]] = requirement["blank_rows"]
        # Bind inter-table gaps only. A relative first table below its title
        # can legitimately have no extra margin, independently of table gaps.
        parameters.setdefault("allOf", []).append({
            "if": {"properties": {"below_range": {"enum": observed_ranges}}, "required": ["below_range"]},
            "then": {"properties": {"blank_rows": gap_schema}, "required": ["blank_rows"]},
        })
    function["description"] += (
        " For stacked pivots pass top-level below_range=<complete preceding output_range> and blank_rows=<requested count>. "
        "Do not JSON-encode an object inside destination. Headers and totals already belong to output_range; "
        "do not add another header row or margin. The final gate checks the actual number of separator rows."
    )


def retry_matches(issue: dict, args: dict) -> bool:
    from calc_adapter.schema import pivot_destination
    from calc_adapter.errors import AdapterError

    try:
        destination = pivot_destination(args)
    except AdapterError:
        return False
    expected = issue["expected"]
    if isinstance(destination, dict):
        return (rectangle(destination.get("below_range")) == rectangle(expected.get("below_range"))
                and _gap_matches(destination.get("blank_rows", -1), expected))
    return bool(expected.get("destination") and rectangle(destination) == rectangle(expected["destination"]))
