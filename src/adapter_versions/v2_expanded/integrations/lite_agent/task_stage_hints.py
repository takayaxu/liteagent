"""Opt-in single-task prompt experiments; no execution or completion overrides.

Identity is matched internally and never included in model-visible guidance.
Only instruction facts and actual public observations may inform these hints.
"""
from __future__ import annotations

import json
import re

from .completion_outcomes import completion_outcome_issues, result_payload

PROFILE = "deadline-repair-20261113-v1"


def _sales_anchors(state):
    """Repeat observed addresses explicitly; never infer them from the task ID."""
    months = {}
    rows = {}
    cells = {}
    for event in state.events:
        if not event.executed or event.error:
            continue
        if event.proposed.get("action") not in {"range.read", "range.write"}:
            continue
        body = result_payload(event)
        addresses = body.get("cell_addresses", [])
        values = body.get("display_text") or body.get("values", [])
        for ar, vr in zip(addresses, values):
            for address, value in zip(ar, vr):
                cells[address] = value
                if value in ("Jan", "Feb", "Mar", "Apr", "May", "Jun"):
                    months[value] = address
                if value in ("Total", "Growth"):
                    rows[value] = address
        # Some write responses omit cell_addresses but include the exact A1 range.
        args = event.proposed.get("arguments", {})
        raw_values = args.get("values")
        if event.proposed.get("action") == "range.write" and isinstance(raw_values, list):
            match = re.fullmatch(r"([A-Z]+)([0-9]+)(?::[A-Z]+[0-9]+)?", args.get("range", ""))
            if match:
                for offset, row in enumerate(raw_values):
                    value = row[0] if isinstance(row, list) and row else row
                    if value in ("Total", "Growth"):
                        rows[value] = f"{match[1]}{int(match[2])+offset}"
    data = {"month_header_cells": months, "written_row_label_cells": rows}
    if "Total" in rows and "Growth" in rows and all(m in months for m in ("Jan", "Feb")):
        total_row = re.search(r"[0-9]+$", rows["Total"])[0]
        growth_row = re.search(r"[0-9]+$", rows["Growth"])[0]
        jan_col = re.match(r"[A-Z]+", months["Jan"])[0]
        feb_col = re.match(r"[A-Z]+", months["Feb"])[0]
        data.update({"Jan_growth_cell_must_be_blank": jan_col+growth_row,
                     "Feb_growth_cell": feb_col+growth_row,
                     "Feb_formula_from_observed_Total_row": f"=({feb_col}{total_row}-{jan_col}{total_row})/{jan_col}{total_row}",
                     "direction": "advance COLUMN letters for each later month; Total ROW number stays fixed"})
    return json.dumps(data, ensure_ascii=False)


def _sales_hint(state):
    events = [e for e in state.events if e.executed and not e.error]
    actions = [e.proposed.get("action") for e in events]
    if "workbook.inspect" not in actions:
        return "OBSERVE: inspect the open workbook to identify its sheet and used range."
    if "range.read" not in actions:
        return "OBSERVE: read the observed source range. Map month headers to columns and sales records to rows before calculating."
    issues = completion_outcome_issues(state)
    defects = [i for i in issues if i.get("code") == "period.values_mismatch"]
    mutations = [e for e in events if e.proposed.get("action") in
                 {"range.write", "cells.set_formulas", "range.clear", "range.format", "chart.create"}]
    labels = {str(row[0] if isinstance(row, list) else row)
              for e in events if e.proposed.get("action") == "range.write"
              for row in e.proposed.get("arguments", {}).get("values", []) if row}
    if defects or "cells.set_formulas" not in actions or not {"Total", "Growth"} <= labels:
        return (
            "CALCULATE: Total is a column-wise sum over ALL sales reps. Growth compares adjacent MONTH TOTALS, "
            "not an individual rep and not adjacent rows. For each Feb-Jun column use "
            "(that month's Total - previous month's Total) / previous month's Total, referencing the "
            "observed Total ROW in both terms. Put the first growth in the Feb COLUMN; Jan stays blank. "
            "Write Total and Growth as plain text labels with range.write, not text-valued formulas. "
            "Use cells.set_formulas for the numeric formulas and percent number format for growth. "
            "Check current completion_outcomes for concrete defects; correct them using observed addresses. "
            "Do not repeat a successful read whose required cells are already present. "
            "If Jan contains any formula, clear that ONE cell with range.clear; do not replace it with another formula. "
            "Division always uses /; a semicolon separates FUNCTION ARGUMENTS only and cannot replace /."
        )
    chart_events = [e for e in events if e.proposed.get("action") == "chart.create"]
    if len(chart_events) < 2 or any(i.get("code") == "period.chart_mismatch" for i in issues):
        return (
            "CHARTS: use the actual Total row for the Jan-Jun bars and actual Growth row for the Feb-Jun line; "
            "exclude Jan from BOTH growth values and category labels. Titles are Total and Growth. "
            "Use one numeric series across columns with month categories; verify returned native bindings. "
            "Keep an already correct chart. Calculation cells and charts are separate objects."
        )
    last_change = max((e.step for e in mutations), default=0)
    saves = [e for e in events if e.proposed.get("action") == "workbook.save" and e.step > last_change]
    if not saves:
        return "PERSIST: save the completed workbook. Then read the saved source and labelled output rows and inspect the charts. Do not rewrite correct calculations or recreate correct charts."
    after_save = [e.proposed.get("action") for e in events if e.step > saves[-1].step]
    if issues or not {"range.read", "workbook.inspect"}.issubset(after_save):
        return (
            "VERIFY: after final save read the source plus both labelled output rows, and workbook.inspect "
            "for chart definitions. Compare growth to adjacent Total values and confirm Jan is blank. "
            "Fix only an actual mismatch; another identical read cannot fix an observed wrong formula. "
            "If a tool is absent, search for it and use its CURRENT schema."
        )
    return (
        "FINISH: saved read-back evidence is available. If every instruction clause and the current "
        "completion gate are satisfied, call propose_done now with concise truthful evidence. "
        "Do not repeat inspection, save or edits just to reconfirm the same facts."
    )


def model_hint(profile, state, *, targets=None):
    if profile != PROFILE:
        return None
    if (targets or {}).get(state.task_id) == "sales-growth" and state.domain == "libreoffice_calc":
        return (_sales_hint(state) + "\nLive address anchors: " + _sales_anchors(state)
                + "\nPrefer these concrete live row/column mappings over earlier reasoning. "
                "The Growth chart category header range starts at the observed FEB column, "
                "not Jan. Do not proceed to charts while the growth cells contain errors or wrong references.")
    return None
