"""Present native mutation evidence with labels from prior cell observations."""
from __future__ import annotations

import copy
import re
from typing import Any


def _position(address: Any) -> tuple[int, int] | None:
    match = re.fullmatch(r"\$?([A-Za-z]+)\$?([1-9][0-9]*)", str(address))
    if not match:
        return None
    column = 0
    for letter in match[1].upper():
        column = column * 26 + ord(letter) - ord("A") + 1
    return column, int(match[2])


def with_calc_mutation_labels(events: list[Any]) -> list[Any]:
    grids: dict[tuple[str, str], dict[tuple[int, int], dict[str, Any]]] = {}
    projected = []
    workbook = ""
    for event in events:
        result = getattr(event, "result", None)
        hint = result.get("context_hint") if isinstance(result, dict) else None
        if not getattr(event, "executed", False) or not isinstance(hint, dict):
            projected.append(event)
            continue
        if hint.get("workbook_url"):
            workbook = hint["workbook_url"]
        elif hint.get("url") and isinstance(hint.get("sheets"), list):
            workbook = hint["url"]
        sheet = hint.get("sheet")
        grid = grids.setdefault((workbook, sheet), {})
        mutation = hint.get("mutation_observation")
        matrices = hint.get("cell_addresses")
        if isinstance(matrices, list) and not isinstance(mutation, dict):
            for i, row in enumerate(matrices):
                if not isinstance(row, list):
                    continue
                for j, address in enumerate(row):
                    position = _position(address)
                    if position is None:
                        continue
                    cell = {"cell": address}
                    for key in ("display_text", "values", "formulas", "kinds"):
                        matrix = hint.get(key)
                        if isinstance(matrix, list) and i < len(matrix) and isinstance(matrix[i], list) and j < len(matrix[i]):
                            cell[key] = matrix[i][j]
                    grid[position] = cell
        if not isinstance(mutation, dict):
            action = getattr(event, "proposed", {}).get("action")
            if action not in {"range.read", "workbook.inspect", "workbook.save", "chart.create"}:
                grids.clear()
            projected.append(event)
            continue
        mutation = copy.deepcopy(mutation)

        def labels(cell_sheet, address):
            source_grid = grids.get((workbook, cell_sheet), {})
            position = _position(address)
            if position is None:
                return {"row_text_left": None, "column_text_above": None}
            column, row = position
            left, above = [], []
            for (c, r), value in source_grid.items():
                if value.get("kinds") != "string" or not value.get("display_text"):
                    continue
                record = {"cell": value.get("cell"), "text": value["display_text"]}
                if r == row and c < column:
                    left.append((c, record))
                if c == column and r < row:
                    above.append((r, record))
            return {
                "row_text_left": max(left, key=lambda x: x[0])[1] if left else None,
                "column_text_above": max(above, key=lambda x: x[0])[1] if above else None,
            }

        for target in mutation.get("targets", []):
            target.update(labels(sheet, target["cell"]))
            before, after = target["before"], target["after"]
            target["overwrote_nonblank"] = before.get("kind") != "blank" and before != after
            for reference in target.get("references", {}).get("cells", []):
                reference.update(labels(reference["sheet"], reference["cell"]))
        for target in mutation.get("targets", []):
            position = _position(target["cell"])
            if position is not None:
                after = target["after"]
                grid[position] = {
                    "cell": target["cell"], "kinds": after["kind"],
                    "display_text": after["display_text"],
                }
        if mutation.get("targets_omitted_count"):
            # This bounded receipt cannot update every changed position. Drop
            # cached labels rather than reusing stale text on later writes.
            grids.clear()
        clone = copy.copy(event)
        clone.result = {**result, "context_hint": {**hint, "mutation_observation": mutation}}
        projected.append(clone)
    return projected
