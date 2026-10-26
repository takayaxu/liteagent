"""Check explicit extremum font requests from current native column evidence."""
from __future__ import annotations

import math
import re

from .completion_outcomes import _complete_rows, _events, _issue, _same_document, _used_rectangle, rectangle
from .completion_policy import action_is_read_only, action_is_save
from .calc_scaled_outcomes import _column, _source_touched
from .instruction_semantics import requested_calculated_column_header

ACTIONS = ("workbook.inspect", "range.read", "range.format", "workbook.save")


def _request(instruction):
    header = requested_calculated_column_header(instruction)
    # The shared helper returns the first header; this contract requires one
    # unambiguous output and a positive, explicit font-color clause.
    if (not header or len(re.findall(r"\bnew\s+columns?\b", instruction, re.I)) != 1
            or re.search(r"\bnew\s+columns\b|\b(?:another|second|additional)\s+(?:new\s+)?column\b", instruction, re.I)
            or re.search(r"\b(?:not|never|avoid|without|unless|if|maybe|perhaps|optionally|consider|possibly|(?:do|does|should|must|would|could)n['’]t)\b[^.;!?]*\b(?:highlight|mark|colou?r)\b", instruction, re.I)):
        return None
    extrema = re.findall(r"\b(highest|maximum|lowest|minimum)\b", instruction, re.I)
    colors = re.findall(r"#[0-9a-f]{6}\b", instruction, re.I)
    clause = re.search(r"\b(?:highlight|mark|colou?r)\s+(?:the\s+)?(?:highest|maximum|lowest|minimum)\s+(?:results?|values?|outputs?)\b[^.!?;]*?(#[0-9a-f]{6})\b[^.!?;]*?\bfont\b", instruction, re.I)
    if len(extrema) != 1 or len(colors) != 1 or not clause:
        return None
    return {"header": header.casefold(), "function": "MAX" if extrema[0].lower() in {"highest", "maximum"} else "MIN",
            "color": clause[1].lower(),
            "number": bool(re.search(r"\b(?:convert|format)\b.*\b(?:as|to)\s+(?:a\s+)?number\s+type\b", instruction, re.I))}


def _style_touched(action, args, sheet, column, row):
    if action == "range.format":
        if args.get("sheet") != sheet:
            return False
        areas = args.get("ranges") or [args.get("range")]
        return any(not (rect := rectangle(area)) or rect[0] <= column <= rect[2] and rect[1] <= row <= rect[3]
                   for area in areas)
    return _source_touched(action, args, sheet, column, row, row)


def _observations(events):
    cells, baseline = {}, {}
    for event, action, args, payload in events:
        if not _same_document(events, event, payload):
            continue
        mutation = payload.get("mutation_observation", {})
        for item in mutation.get("targets", []):
            rect = rectangle(item.get("cell"))
            before = item.get("before", {})
            if rect and mutation.get("sheet"):
                key = (mutation["sheet"], rect[0], rect[1])
                if not any(e.step < event.step and _style_touched(a, ar, *key) for e, a, ar, _ in events):
                    baseline.setdefault(key, before.get("styles"))
        sheet, area, snapshot = payload.get("sheet", args.get("sheet")), payload.get("range", args.get("range")), payload
        if isinstance(payload.get("readback"), dict):
            snapshot = payload["readback"]
            sheet = payload.get("sheet", payload.get("destination_sheet"))
            area = payload.get("range", payload.get("destination_range"))
        elif action != "range.read" and action != "range.write":
            continue
        rect = rectangle(area)
        if not sheet or _complete_rows(snapshot, rect) is None:
            continue
        if action == "range.read" and (sheet != args.get("sheet") or rect != rectangle(args.get("range"))):
            continue
        for r in range(rect[3] - rect[1] + 1):
            for c in range(rect[2] - rect[0] + 1):
                cell = {"step": event.step}
                for name in ("values", "kinds", "result_types", "styles", "number_formats", "display_text"):
                    matrix = snapshot.get(name)
                    if isinstance(matrix, list) and r < len(matrix) and isinstance(matrix[r], list) and c < len(matrix[r]):
                        cell[name] = matrix[r][c]
                key = (sheet, rect[0] + c, rect[1] + r)
                cells[key] = cell
                # Only a read preceding every possible mutation establishes an original style.
                if not any(e.step < event.step and _style_touched(a, ar, *key)
                           for e, a, ar, _ in events):
                    baseline.setdefault(key, cell.get("styles"))
    return cells, baseline


def _base_color(style):
    if not isinstance(style, dict):
        return None
    cf = style.get("conditional_format", {})
    if cf.get("status") == "known" and cf.get("count") == 0 and cf.get("rules") == []:
        return style.get("font_color")
    return None


def _effective_color(style, sheet, column, row, first, last, value, extreme, function):
    if not isinstance(style, dict):
        return None
    cf = style.get("conditional_format", {})
    if cf.get("status") != "known":
        return None
    if cf.get("count") == 0 and cf.get("rules") == []:
        return style.get("font_color")
    rules = cf.get("rules")
    if cf.get("count") != 1 or not isinstance(rules, list) or len(rules) != 1:
        return None
    rule = rules[0]
    if rule.get("operator") != "formula" or rule.get("formula2") not in {"", "0"} or not rule.get("font_color"):
        return None
    # Conservative single formula: a relative/absolute self reference equals
    # MAX/MIN of the entire absolute current column. No expression evaluation.
    formula = re.sub(r"\s+", "", str(rule.get("formula1", ""))).lstrip("=")
    match = re.fullmatch(r"(\$?[A-Za-z]+)(\$?[1-9]\d*)=(MAX|MIN)\((\$[A-Za-z]+\$[1-9]\d*):(\$[A-Za-z]+\$[1-9]\d*)\)", formula, re.I)
    pos = rule.get("source_position", {})
    if not match or match[3].upper() != function or pos.get("sheet") != sheet:
        return None
    if not all(isinstance(pos.get(k), int) and not isinstance(pos[k], bool) for k in ("row", "column")):
        return None
    left = rectangle(match[1] + match[2])
    bounds = rectangle(match[4] + ":" + match[5])
    effective_column = left[0] + (column - pos["column"] if not match[1].startswith("$") else 0)
    effective_row = left[1] + (row - pos["row"] if not match[2].startswith("$") else 0)
    if (effective_column, effective_row) != (column, row) or bounds != (column, first, column, last):
        return None
    return rule["font_color"] if value == extreme else style.get("font_color")


def _numeric_format(details):
    if not isinstance(details, dict) or not isinstance(details.get("type"), int):
        return None
    # UNO NumberFormat: NUMBER=16, SCIENTIFIC=32, FRACTION=64; DEFINED=1 may be combined.
    kind = details["type"] & ~1
    return kind in {16, 32, 64}  # General reports NUMBER on native Calc.


def outcome_issues(state):
    spec = _request(str(state.instruction))
    if not spec:
        return []
    events = _events(state)
    mutations = [(e, a, args) for e, a, args, _ in events
                 if not action_is_read_only(a) and not action_is_save(a)]
    if not mutations:
        return []
    cells, baseline = _observations(events)
    target = {"header": spec["header"]}

    def issue(code, expected, observed, mismatch=False):
        return _issue("extremum." + code, target, expected, observed, actions=ACTIONS, mismatch=mismatch)

    headers = [key for key, cell in cells.items()
               if isinstance(cell.get("values"), str) and cell["values"].strip().casefold() == spec["header"]]
    if len(headers) != 1:
        return [issue("column_unverified", "read one uniquely named output column and its complete numeric extent", {"matching_headers": len(headers)})]
    sheet, column, header_row = headers[0]
    inspections = [(e, p) for e, a, _, p in events if a == "workbook.inspect" and _same_document(events, e, p)]
    latest = inspections[-1] if inspections else None
    extent = next((_used_rectangle(s) for s in latest[1].get("sheets", []) if s.get("name") == sheet), None) if latest else None
    target.update(sheet=sheet)
    if (not extent or extent[1] != header_row or not extent[0] <= column <= extent[2]
            or latest[1].get("context_truncated") or latest[1].get("sheets_omitted_from_context")):
        return [issue("extent_unverified", "native used extent of one table beginning with the output header", None)]
    first, last = header_row + 1, extent[3]
    target["range"] = f"{_column(column)}{first}:{_column(column)}{last}"
    # Require fresh inventory, header and full numeric/style readback. Unknown
    # writes and GUI actions invalidate all evidence, including formula inputs.
    after = max([e.step for e, _, _ in mutations] + [e.step for e, a, _, _ in events if action_is_save(a)])
    header = cells[headers[0]]
    header_change = max((e.step for e, a, args in mutations if _source_touched(a, args, sheet, column, header_row, header_row)), default=0)
    if latest[0].step <= after or header["step"] < header_change:
        return [issue("column_unverified", "inspect current used extent and read header after any content change", None)]
    values, missing = {}, []
    for row in range(first, last + 1):
        cell = cells.get((sheet, column, row), {})
        value = cell.get("values")
        if (cell.get("step", 0) <= after or not isinstance(value, (int, float))
                or isinstance(value, bool) or not math.isfinite(value)
                or cell.get("kinds") not in {"number", "formula"}
                or (cell.get("kinds") == "formula" and cell.get("result_types") != "number")):
            missing.append(f"{_column(column)}{row}")
        else:
            values[row] = value
    if missing or not values:
        return [issue("values_unverified", "read complete current native numeric values, result types, styles and formats after changes/save", {"unverified_cells": missing})]
    extreme = (max if spec["function"] == "MAX" else min)(values.values())
    wrong, unknown, formats = [], [], []
    for row, value in values.items():
        key = (sheet, column, row)
        address = f"{_column(column)}{row}"
        color = _effective_color(cells[key].get("styles"), sheet, column, row, first, last, value, extreme, spec["function"])
        if color is None:
            unknown.append(address)
        elif value == extreme and color != spec["color"]:
            wrong.append({"cell": address, "value": value, "font_color": color, "required_color": spec["color"]})
        elif value != extreme and color == spec["color"]:
            original = _base_color(baseline.get(key))
            if original is None:
                unknown.append(address)
            elif original != spec["color"]:
                wrong.append({"cell": address, "value": value, "font_color": color, "original_color": original,
                              "reason": "requested color newly applied to a non-extreme value; preserve existing styles"})
        if spec["number"]:
            numeric = _numeric_format(cells[key].get("number_formats"))
            if numeric is None:
                unknown.append(address)
            elif not numeric:
                formats.append({"cell": address, "format": cells[key].get("number_formats")})
    issues = []
    if wrong:
        issues.append(issue("font_mismatch", {"extreme_value": extreme, "extreme_cells": [f"{_column(column)}{r}" for r, v in values.items() if v == extreme], "font_color": spec["color"], "other_cells": "preserve original fonts; repair only newly introduced incorrect highlighting"}, {"wrong_cells": wrong}, True))
    if formats:
        issues.append(issue("number_format_mismatch", "numeric values displayed with a number format as requested", {"wrong_cells": formats}, True))
    if unknown:
        issues.append(issue("styles_unverified", "complete effective font evidence; supported single MAX/MIN conditional rule or no conditional formatting, original styles for extra highlighting", {"unverified_cells": list(dict.fromkeys(unknown))}))
    return issues
