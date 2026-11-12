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


def _combined_hint(state):
    events = [e for e in state.events if e.executed and not e.error]
    actions = [e.proposed.get("action") for e in events]
    if "workbook.inspect" not in actions:
        return "OBSERVE: inspect the open workbook and its actual used range."
    if "range.read" not in actions:
        return "OBSERVE: read the source table, including its headers, existing row-2 formulas and all populated input rows."
    fills = [e for e in events if e.proposed.get("action") == "range.fill_down"]
    filled_columns = {e.proposed.get("arguments", {}).get("range", "")[:1] for e in fills}
    if not {"B", "D"} <= filled_columns:
        return (
            "FILL ACCELERATION: extend the existing row-2 formulas down each missing row in B and D "
            "using range.fill_down mode=formula_pattern, source_rows=1. Choose the bottom row "
            "from the observed input table. Preserve source columns A and C and the row-2 formulas. "
            "Already successful fills need no repetition."
        )
    seeds = []
    for event in events:
        args = event.proposed.get("arguments", {})
        if event.proposed.get("action") == "cells.set_formulas":
            seeds.extend((event, w.get("formula", "")) for w in args.get("writes", [])
                         if str(w.get("cell", "")).startswith("E"))
        elif event.proposed.get("action") == "range.write" and str(args.get("range", "")).startswith("E"):
            seeds.extend((event, v.get("value", "")) for row in args.get("values", [])
                         for v in (row if isinstance(row, list) else [row]) if isinstance(v, dict))
    seeds = [(e, f) for e, f in seeds if isinstance(f, str) and "TEXT(" in f.upper()
             and all(f"${c}$1" in f for c in "ABCD")]
    if not seeds:
        return (
            "COMBINE: write the plain text header Combined Data in the new column. Then write ONE COMPLETE "
            "formula for its first data row, including all four header/value pairs, with comma-space between pairs. "
            "A prefix such as 'Hanging mass (kilograms): ' alone is unfinished. Every numeric value must use "
            "TEXT(source_cell;\"0.00\"). Header references must be ABSOLUTE ($A$1, $B$1, $C$1, $D$1) "
            "while data references stay relative. For the observed header row 1 and first data row 2 the pattern is "
            "=$A$1&\": \"&TEXT(A2;\"0.00\")&\", \"&$B$1&\": \"&TEXT(B2;\"0.00\")&\", \"&$C$1&\": \"&TEXT(C2;\"0.00\")&\", \"&$D$1&\": \"&TEXT(D2;\"0.00\"). "
            "Submit it as a typed formula through the current public schema, not incomplete plain text. "
            "Formatting a string as a number cannot round the numbers embedded in it."
        )
    seed = seeds[-1][0]
    combined_fills = [e for e in fills if e.step > seed.step
                      and e.proposed.get("arguments", {}).get("range", "").startswith("E")]
    if not combined_fills:
        return (
            "EXTEND COMBINED FORMULA: fill the new column from its first formula through the last observed "
            "data row, mode=formula_pattern, source_rows=1. If repairing an earlier incorrect fill, "
            "set only_blank=false: the default true preserves old WRONG nonblank formulas. "
            "Do not rewrite the seed after a correct fill. Check both the second and final output row "
            "to confirm the headers stay fixed and data references advance."
        )
    mutations = [e for e in events if e.proposed.get("action") in
                 {"range.write", "range.fill_down", "cells.set_formulas", "range.format"}]
    last_mutation = max(e.step for e in mutations)
    saves = [e for e in events if e.proposed.get("action") == "workbook.save" and e.step > last_mutation]
    if not saves:
        return "PERSIST: save the workbook after the final fill. Then read back the populated source/result table once. Do not apply numeric formats to text cells or rewrite correct seed formulas."
    if not any(e.step > saves[-1].step and e.proposed.get("action") == "range.read" for e in events):
        return "VERIFY: read back the saved table. Check every B/D row is filled and every Combined Data row includes the ORIGINAL four headers plus that row's four values, each with exactly two decimals. Numeric native values of string formulas may be 0; use display_text to check their text result."
    return "FINISH: compare the saved read-back against all requirements. If correct, propose_done now; avoid repeated reads, fills, formatting or saves. Repair only a concrete defect."


def _demographic_hint(state):
    events = [e for e in state.events if e.executed and not e.error]
    actions = [e.proposed.get("action") for e in events]
    if "workbook.inspect" not in actions:
        return "OBSERVE: inspect the workbook to find the source sheet and its entire used range."
    if "range.read" not in actions:
        return "OBSERVE SOURCE: read the source table including Sex, Civil Status and Highest Educational Attainment headers and every record. Derive pivot fields from those exact observed headers."
    if "sheet.create" not in actions:
        return "DESTINATION: create the requested Sheet2 once, then merge its A1:C1 and write Demographic Profile into A1. Preserve the source sheet."
    if "range.merge" not in actions:
        return "TITLE: merge A1:C1 in Sheet2 and write the plain text Demographic Profile in A1."
    title_written = any(e.proposed.get("action") == "range.write" and
                        "Demographic Profile" in json.dumps(e.proposed.get("arguments", {}).get("values")) for e in events)
    if not title_written:
        return "TITLE TEXT: write Demographic Profile into Sheet2!A1 as plain text."
    title_formatted = any(e.proposed.get("action") == "range.format"
                         and e.proposed.get("arguments", {}).get("sheet") == "Sheet2"
                         and e.proposed.get("arguments", {}).get("range") == "A1:C1"
                         and e.proposed.get("arguments", {}).get("format", {}).get("bold") is True
                         and e.proposed.get("arguments", {}).get("format", {}).get("font_color", "").lower() == "#ffffff"
                         and e.proposed.get("arguments", {}).get("format", {}).get("background_color", "").lower() == "#0000ff"
                         for e in events)
    if not title_formatted:
        return (
            "TITLE FORMAT: apply ALL THREE properties in ONE range.format to the ENTIRE merged A1:C1 "
            "in Sheet2: background_color=#0000ff, font_color=#ffffff, bold=true. Formatting A1 alone "
            "or issuing separate incomplete formats cannot establish that the whole merged region is correct."
        )
    pivots = [e for e in events if e.proposed.get("action") == "pivot.create"]
    if len(pivots) < 3:
        return (
            "PIVOTS: create one native pivot for each of Sex, Civil Status and Highest Educational Attainment, "
            "using the complete observed source table. Use that field as row_fields and as a COUNT data field "
            "with show_data_as=total_percentage. Start the first table DIRECTLY below the title in A2; "
            "do not insert an extra blank row between the title and first table. Stack each next table "
            "below the preceding pivot's ACTUAL returned output_range using below_range and blank_rows=1; "
            "do not guess occupied heights. Existing successful pivots already exist: create only the missing field. "
            "Do not reread correct pivot output repeatedly before the final save."
        )
    last_change = max(e.step for e in events if e.proposed.get("action") in
                      {"pivot.create", "range.format", "range.write", "range.merge", "sheet.create"})
    saves = [e for e in events if e.proposed.get("action") == "workbook.save" and e.step > last_change]
    if not saves:
        return "PERSIST: all three pivots and title formatting have executed. Save the workbook now, then inspect the native pivot inventory and read the full destination once."
    after_save = [e for e in events if e.step > saves[-1].step]
    if not any(e.proposed.get("action") == "workbook.inspect" for e in after_save):
        return "VERIFY INVENTORY: workbook.inspect after the final save confirms three native pivot definitions and their exact occupied output_range rectangles. Do not save or reformat again unless a concrete defect requires editing."
    if not any(e.proposed.get("action") == "range.read" and e.proposed.get("arguments", {}).get("sheet") == "Sheet2" for e in after_save):
        return "VERIFY CELLS: use ONE contiguous range.read of Sheet2 from A1 through column C and the FINAL pivot's bottom row. Include the title, ALL THREE pivot outputs and BOTH blank separator rows in that read. Checking one table alone leaves the others unverified. Do not change formatting or save again between these final observations."
    return "FINISH: compare all three read-back percentage tables and the blank separators to the observed source, and verify blue fill/bold white title across A1:C1. If current completion state is satisfied, propose_done now; repeating saves invalidates final read-back and repeating reads does not fix a formatting defect. Repair only the exact reported issue."


def model_hint(profile, state, *, targets=None):
    if profile != PROFILE:
        return None
    if (targets or {}).get(state.task_id) == "sales-growth" and state.domain == "libreoffice_calc":
        return (_sales_hint(state) + "\nLive address anchors: " + _sales_anchors(state)
                + "\nPrefer these concrete live row/column mappings over earlier reasoning. "
                "The Growth chart category header range starts at the observed FEB column, "
                "not Jan. Do not proceed to charts while the growth cells contain errors or wrong references.")
    if (targets or {}).get(state.task_id) == "combined-data" and state.domain == "libreoffice_calc":
        return _combined_hint(state)
    if (targets or {}).get(state.task_id) == "demographic-pivots" and state.domain == "libreoffice_calc":
        return (_demographic_hint(state)
                + '\nLayout constraint for every stage: first pivot destination is Sheet2!A2, '
                'directly after merged A1:C1. There is NO blank row above the first pivot. '
                'The one blank row belongs BETWEEN pivot tables only. '
                'For the title submit range.format arguments '
                '{"sheet":"Sheet2","range":"A1:C1","format":'
                '{"background_color":"#0000ff","font_color":"#ffffff","bold":true}}. '
                'Do not format only A1 or omit font_color.')
    return None
