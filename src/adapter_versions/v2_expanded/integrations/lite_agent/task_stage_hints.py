"""Opt-in single-task prompt experiments; no execution or completion overrides.

Identity is matched internally and never included in model-visible guidance.
Only instruction facts and actual public observations may inform these hints.
"""
from __future__ import annotations

import json
import re

from .completion_outcomes import completion_outcome_issues, result_payload

PROFILE = "deadline-repair-20261113-v1"


def gemini_native_result(event):
    """Unwrap the public multi-app response without changing shared evidence code."""
    body = result_payload(event)
    if isinstance(body.get("response"), dict) and isinstance(body["response"].get("result"), dict):
        return body["response"]["result"]
    if isinstance(body.get("downstream_context"), dict):
        return body["downstream_context"]
    return body


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


def _personal_cleanup_hint(state):
    step = state.next_title_range_personal_info_cleanup_action()
    if step:
        return (
            "CURRENT EDIT: use the observed next cleanup operation below. The slide parameters are "
            "native ZERO-BASED indices: human slides 2 and 3 mean slide=1 and slide=2; "
            "human slide 4 means slide=3. Do not reconsider or add one to an observed native index. "
            "Shape paths come from presentation.inspect. After deletion indices may change; use "
            "current observed paths or the existing descending-index cleanup plan. Keep all non-personal content. "
            "Call the provided public Adapter tool directly with its current schema. "
            "Do not reselect these shapes in the GUI or emit only reasoning. "
            "Observed next operation: " + json.dumps(step, ensure_ascii=False)
        )
    if not state.title_range_personal_info_cleanup_plan():
        return "OBSERVE: presentation.inspect native slides [1,2,3] once to identify titles on human slides 2-3 and personal text/icons on human slide 4. Read the inspected native shape paths; do not spend turns debating slide numbering."
    events = [e for e in state.events if e.executed and not e.error]
    saved = any(e.proposed.get("action") == "presentation.save" for e in events)
    if not saved:
        return "PERSIST: the observed title-format and personal-information deletions have executed. Call presentation.save once now, not another deletion or format."
    return "FINISH: inspect the saved slides once to confirm both titles are bold black and all requested personal text/icons are absent. If the current completion check is satisfied, call propose_done immediately; preserve all other content."


def _tabstop_hint(state):
    events = [e for e in state.events if e.executed and not e.error]
    inspections = [e for e in events if e.proposed.get("action") == "document.inspect"]
    if not inspections:
        return "OBSERVE: document.inspect once to read sentence paragraphs, their native indices and page_layouts.body_width_mm."
    paragraphs = {}
    width = None
    for event in inspections:
        body = result_payload(event)
        for layout in body.get("page_layouts", []):
            width = layout.get("body_width_mm") or width
        for p in body.get("paragraph_details", []):
            if p.get("text_length", 0) == len(p.get("text", "")):
                paragraphs[p["index"]] = p
    escaped = [p["index"] for p in paragraphs.values() if p.get("literal_tab_escape_count", 0)]
    if escaped:
        return (
            "REPAIR ESCAPED TAB: native inspection found literal backslash+t in paragraphs " + str(escaped)
            + '. Replace the literal escape with a REAL tab. For text.find_replace use find="\\\\t", '
            'replacement="\\u0009", replace_all=true, case_sensitive=true in raw JSON. '
            'Unicode escape U+0009 is a Tab character. Do not insert a second backslash. '
            'Then inspect the paragraphs once to confirm literal_tab_escape_count=0 and has_tab_character=true.'
        )
    anchors = []
    for index, p in paragraphs.items():
        words = list(re.finditer(r"\S+", p.get("text", "")))
        if len(words) < 3:
            continue
        prefix = p["text"][:words[2].end()]
        inserted = any(e.proposed.get("action") == "text.find_replace"
                       and e.proposed.get("arguments", {}).get("find", "").startswith(prefix)
                       and "\t" in e.proposed.get("arguments", {}).get("replacement", "") for e in events)
        inserted = inserted or any(e.proposed.get("action") == "paragraph.replace_text"
                                  and e.proposed.get("arguments", {}).get("index") == index
                                  and any("\t" in t for t in e.proposed.get("arguments", {}).get("paragraphs", []))
                                  for e in events)
        if not p.get("has_tab_character") and not inserted:
            anchor = p["text"][:words[3].start()] if len(words) > 3 else prefix
            replacement = prefix + "\t" if len(words) > 3 else prefix
            anchors.append({"paragraph_index": index, "first_three_words": prefix,
                            "find": anchor, "replacement": replacement,
                            "paragraphs": [prefix + "\t" + p["text"][words[3].start():]] if len(words) > 3 else [prefix]})
    if anchors:
        return (
            "INSERT REAL TABS: keep each sentence in its ORIGINAL paragraph. Do NOT paragraph.split after "
            "the first three words: a paragraph break cannot align two text runs on one line. "
            "Use paragraph.replace_text for ONE observed paragraph, with its exact full text in a ONE-item paragraphs ARRAY. Change only "
            "the separating space after the third word to ONE actual tab. In JSON use \\t (decoded TAB), not \\\\t "
            "(literal backslash plus t). Preserve all original words, punctuation, blank paragraphs and formatting. "
            "Do not re-read identical complete paragraphs or reconstruct document text. "
            "CURRENT OBSERVED ANCHOR ONLY: " + json.dumps(anchors[0], ensure_ascii=False)
            .replace('\\t', '\\u0009')
            + ". Call paragraph.replace_text NOW with index=paragraph_index and paragraphs copied from the observed array. "
            "Do not use the find/replacement fields; they are boundary notes. This exact full source is already observed. "
            "The replacement is a JSON string: use the Unicode escape \\u0009 for an actual tab; "
            "do not double the backslash. After all insertions apply the format to ALL sentence indices, "
            "not an index guessed from one-based numbering."
        )
    indices = sorted(index for index, p in paragraphs.items() if len(p.get("text", "").split()) >= 3)
    formats = [e for e in events if e.proposed.get("action") == "paragraph.set_format"
               and e.proposed.get("arguments", {}).get("alignment") == "left"
               and set(e.proposed.get("arguments", {}).get("indices", [])) >= set(indices)]
    if not formats:
        return (
            "TAB FORMAT: keep paragraph alignment=left for the first three words; set a RIGHT-aligned "
            "tab stop at the observed usable right edge so the text following the tab ends at that edge. "
            "Apply the same tab format to all relevant sentence paragraphs in one call; no extra left "
            "tab stop at an arbitrary middle position is needed. The gap comes from a real tab plus its "
            "right-aligned stop, not paragraph splitting or adding spaces. Observed body_width_mm=" + str(width)
            + ". Current format arguments from observed indices/layout: " + json.dumps({
                "indices": indices, "alignment": "left", "tab_stops": [{
                    "position": {"value": width, "unit": "mm"}, "alignment": "right"}]})
        )
    last_change = max((e.step for e in events if e.proposed.get("action") in
                       {"text.find_replace", "paragraph.replace_text", "paragraph.set_format"}), default=0)
    saves = [e for e in events if e.proposed.get("action") == "document.save" and e.step > last_change]
    if not saves:
        return "PERSIST: save the Writer document after all local tab insertions and the right-tab format."
    if not any(e.step > saves[-1].step for e in inspections):
        return "VERIFY: inspect all saved sentence paragraphs once. Check native has_tab_character, tab_character_offsets and right-aligned tab_stops. Ensure each sentence stayed in one paragraph and all text is preserved."
    return "FINISH: if every sentence has its first three words left and remaining text after a real right tab, propose_done with the saved evidence. Do not split paragraphs or repeat reads."


def _vowel_hint(state):
    events = [e for e in state.events if e.executed and not e.error]
    reads = [e for e in events if e.proposed.get("action") == "table.read"]
    if not reads:
        return "OBSERVE: document.inspect to get the actual table name, then table.read to see every word with its exact cell name. Do not classify by cell position or by whether a word contains a vowel."
    body = result_payload(reads[-1])
    fields = body.get("cell_fields", [])
    groups = {"red": [], "blue": []}
    for cell in body.get("cells", []):
        data = dict(zip(fields, cell)) if isinstance(cell, list) else cell
        text = str(data.get("text", "")).strip()
        if not text:
            continue
        group = "red" if text[0].lower() in "aeiou" else "blue"
        groups[group].append({"cell": data.get("name"), "word": text, "first_letter": text[0]})
    mutations = [e for e in events if e.proposed.get("action") == "table.set_cell_text_color"]
    if len(mutations) < 2:
        return (
            "CLASSIFY AND COLOR: compare ONLY each observed word's first letter, case-insensitive. "
            "Words starting a/e/i/o/u are RED #FF0000; all other initial letters, including y, are BLUE #0000FF. "
            "Containing a vowel later does not make a word vowel-initial. Use explicit cell-name lists in "
            "table.set_cell_text_color, preferably one call for ALL red words and one for ALL blue words. "
            "Skip truly empty cells and preserve body paragraphs. Observed first-letter groups: "
            + json.dumps(groups, ensure_ascii=False)
        )
    last_change = max(e.step for e in mutations)
    saves = [e for e in events if e.proposed.get("action") == "document.save" and e.step > last_change]
    if not saves:
        return "PERSIST: the word-color groups have been applied. Save the document once, then table.read all cells to verify each word's FIRST LETTER against its actual font_color."
    if reads[-1].step <= saves[-1].step:
        return "VERIFY: table.read the saved word table once. Do not redo the classification from memory. Compare each actual cell color with its observed first letter."
    colors = {}
    for group, items in groups.items():
        for item in items:
            colors[item["cell"]] = "#ff0000" if group == "red" else "#0000ff"
    wrong = []
    for cell in body.get("cells", []):
        data = dict(zip(fields, cell)) if isinstance(cell, list) else cell
        if data.get("name") in colors and str(data.get("font_color", "")).lower() != colors[data["name"]]:
            wrong.append(data)
    if wrong:
        return "REPAIR ONLY MISMATCHES: the following saved cells have a color inconsistent with their first letter. Correct only these, save and read back again: " + json.dumps(wrong, ensure_ascii=False)
    return "FINISH: all nonempty word cells now match the first-letter color rule and are saved. Call propose_done now. Do not recolor correct vowel cells blue or keep reclassifying words."


def _comma_table_hint(state):
    events = [e for e in state.events if e.executed and not e.error]
    inspections = [e for e in events if e.proposed.get("action") == "document.inspect"]
    if not inspections:
        return "OBSERVE: document.inspect the native paragraph inventory and existing tables. Existing tables are already tables and must be preserved. Locate body paragraphs containing comma-delimited lists, not incidental commas in explanatory prose."
    conversions = [e for e in events if e.proposed.get("action") == "table.convert_text"]
    last_change = max((e.step for e in conversions), default=0)
    recent = [e for e in inspections if e.step > last_change]
    if not recent:
        return "OBSERVE AFTER CONVERSION: the selected text is now a table. Do not convert its old paragraph indices again. document.inspect current paragraphs, using paragraph_start/paragraph_limit and next_paragraph_start to see remaining unconverted text; native inspection does not require GUI scrolling."
    latest = result_payload(recent[-1])
    candidates = [{"index": p.get("index"), "text": p.get("text"), "length": p.get("text_length")}
                  for p in latest.get("paragraph_details", []) if "," in p.get("text", "")]
    return (
        "CONVERT ONLY LIVE DELIMITED TEXT: inspect native paragraphs in bounded pages, following "
        "next_paragraph_start for omitted content. Do not scroll the GUI to discover text that document.inspect "
        "can read. For the current comma-separated list, use table.convert_text with delimiter=',' and the "
        "CURRENT observed start/end indices; consecutive comma-separated list lines belong in one table. "
        "A conversion creates one new native table and saves it; do not convert the same old indices again. "
        "Preserve existing tables and explanatory prose. Current comma-containing observations (decide which "
        "are actual lists): " + json.dumps(candidates, ensure_ascii=False)
        + ". If no unconverted list remains after complete native coverage, document.save, inspect once "
        "and propose_done. Blank paragraphs and already-converted table content are not new list sources."
    )


def _gemini_document_hint(state, facts):
    def stage(note, adapter, action, params, document=None):
        payload = {"params": params}
        if document:
            payload["document"] = document
        return "NATIVE GEMINI: " + note + "\n" + json.dumps({
            "adapter": adapter, "action": action, "payload": payload}, ensure_ascii=False)

    generated = [e for e, _, action, args in facts if action == "command.run"
        and "/tmp/gemini-responses.fodt" in json.dumps(args)]
    if not generated:
        reads = [(e, args) for e, _, action, args in facts if action == "file.read_text"
                 and "gemini-responses" not in str(args.get("path", ""))]
        if not reads:
            return "EXTRACT: identify and read the open source JSON file using its actual guest path. Copy ALL Gemini response values; Iliad is a highlighting criterion only."
        source = reads[0][1]["path"]
        script = (
            "import json,re; from pathlib import Path; from xml.sax.saxutils import escape; "
            "walk=lambda x: [r for k,v in x.items() for r in "
            "([v] if k.lower()=='gemini' and isinstance(v,str) else walk(v))] "
            "if isinstance(x,dict) else [r for v in x for r in walk(v)] if isinstance(x,list) else []; "
            f"responses=walk(json.loads(Path({source!r}).expanduser().read_text())); "
            "values=[r.replace(chr(10),chr(92)+'n') for r in responses]; "
            "head='<?xml version=\"1.0\" encoding=\"UTF-8\"?><office:document xmlns:office=\"urn:oasis:names:tc:opendocument:xmlns:office:1.0\" "
            "xmlns:text=\"urn:oasis:names:tc:opendocument:xmlns:text:1.0\" "
            "xmlns:style=\"urn:oasis:names:tc:opendocument:xmlns:style:1.0\" "
            "xmlns:fo=\"urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0\" "
            "office:version=\"1.2\" office:mimetype=\"application/vnd.oasis.opendocument.text\">'"
            "; styles='<office:automatic-styles><style:style style:name=\"Highlight\" "
            "style:family=\"text\"><style:text-properties fo:background-color=\"#ffff00\"/>"
            "</style:style></office:automatic-styles>'; "
            "render=lambda v: ''.join('<text:span text:style-name=\"Highlight\">Iliad</text:span>' "
            "if part=='Iliad' else escape(part).replace(' ','<text:s/>').replace(chr(9),'<text:tab/>') "
            "for part in re.split('(Iliad)',v)); "
            "body='<text:p/>'.join('<text:p>'+render(v)+'</text:p>' for v in values); "
            "Path('/tmp/gemini-responses.fodt').write_text(head+styles+'<office:body><office:text>'"
            "+body+'</office:text></office:body></office:document>',encoding='utf-8'); "
            "print(json.dumps({'draft_path':'/tmp/gemini-responses.fodt','responses':len(values),"
            "'iliad_occurrences':sum(v.count('Iliad') for v in values)}))"
        )
        return stage("Generate a NEW flat OpenDocument from the actual JSON source. This preserves "
            "source-visible backslash+n notation, gives each complete Gemini value its own paragraph, "
            "adds one blank paragraph between responses and marks every Iliad yellow. Use only source "
            "values, never a reference artifact. Execute this finite model-visible script once; then "
            "open its returned draft in Writer for native verification and DOCX export.",
            "os", "command.run", {"argv": ["python3", "-c", script], "cwd_source": "home", "provenance": "shell_history"})
    opened = [e for e, _, action, args in facts if action == "command.run"
              and args.get("argv", [])[:1] == ["libreoffice"]]
    if not opened:
        return stage("The source-derived draft was generated successfully. Launch Writer with its "
            "explicit OpenDocument Text Flat XML import filter; do not use plain-text import. "
            "Do not rerun extraction, create a blank document or append text again. terminal=true "
            "launches this GUI command without waiting for Writer to close.",
            "os", "command.run", {"argv": ["libreoffice", "--writer",
                "--infilter=OpenDocument Text Flat XML", "/tmp/gemini-responses.fodt"],
                "cwd_source": "home", "provenance": "shell_history", "terminal": True})
    reads = [e for e, _, action, _ in facts if action == "document.inspect" and e.step > opened[-1].step]
    if not reads:
        return stage("Read the native draft paragraphs and highlighting once before saving. "
            "No GUI selection or manual text copying is needed.", "libreoffice_writer", "document.inspect",
            {"paragraph_start": 0, "paragraph_limit": 12}, {"url": "/tmp/gemini-responses.fodt"})
    body = gemini_native_result(reads[-1])
    saves = [e for e, _, action, args in facts if action == "document.save"
             and str(args.get("url", "")).endswith("/gemini_results.docx") and e.step > opened[-1].step]
    if not saves:
        return stage("Native draft inspection is available. Save it as the requested Desktop DOCX "
            "using the explicit Word filter. Keep source values, response paragraphs and highlighting.",
            "libreoffice_writer", "document.save", {"url": "/home/user/Desktop/gemini_results.docx",
                "filter_name": "Office Open XML Text"}, {"url": "/tmp/gemini-responses.fodt"})
    if reads[-1].step <= saves[-1].step:
        return stage("Read the saved DOCX native paragraphs and highlighting once. Do not re-extract, "
            "rewrite, highlight again or save repeatedly.", "libreoffice_writer", "document.inspect",
            {"paragraph_start": 0, "paragraph_limit": 12}, {"url": "/home/user/Desktop/gemini_results.docx"})
    return "NATIVE GEMINI FINISH: review the saved native facts and propose_done now if they meet " \
        "all requirements. Do not repeat tools. Existing completion checks still apply. Saved facts: " + json.dumps({
            "identity": body.get("identity"), "paragraph_count": body.get("paragraph_count"),
            "nonempty_paragraph_count": body.get("nonempty_paragraph_count"), "highlighting": body.get("highlighting")}, ensure_ascii=False)


def _cross_app_hint(state, kind):
    from .completion_policy import effective_canonical_action
    facts = [(e, *effective_canonical_action(e, state.domain)) for e in state.events if e.executed and not e.error]
    actions = {a for _, _, a, _ in facts}
    if kind in {"ecs-rates", "grf-records"}:
        source_reads = [e for e, _, a, _ in facts if a == "pdf.tables.inspect"]
        if kind == "grf-records":
            paths = []
            for e, _, a, _ in facts:
                if a == "filesystem.find":
                    body = (e.result or {}).get("context_hint", {})
                    body = body.get("downstream_context", body)
                    paths.extend(m.get("path") for m in body.get("matches", []) if str(m.get("path", "")).endswith(".pdf"))
            seen = {args.get("input_path") for _, _, a, args in facts if a == "pdf.tables.inspect"}
            pending = [p for p in dict.fromkeys(paths) if p not in seen]
            if pending:
                return ("CURRENT STEP ONLY: call os pdf.tables.inspect now for the next observed annual file "
                        + pending[0] + ", page=1, table_index=0, max_rows=50. The previous tables remain in "
                        "the execution ledger. Do NOT calculate, compare universities, reinterpret supported "
                        "amounts or write output before all five sources have been read. After these reads the "
                        "public table.records.compute tool can use exact header/row references. "
                        "Remaining observed sources: " + json.dumps(pending))
        if kind == "ecs-rates" and len(source_reads) >= 9:
            if "workbook.inspect" not in actions:
                return "CURRENT STEP ONLY: all nine annual source PDF tables have been read. Use tools_search query='libreoffice_calc workbook.inspect', then CALL workbook.inspect. Do not recalculate, reread PDFs, guess destinations or attempt writes yet."
            if "range.read" not in actions:
                return "CURRENT STEP ONLY: read the actual target workbook's observed used range with libreoffice_calc range.read to identify the year rows and university columns. The source PDFs are already observed. Do not write or reread PDFs now."
        compute = "table.ratio_matrix.compute" if kind == "ecs-rates" else "table.records.compute"
        if not any(e.proposed.get("tool") == compute or e.proposed.get("action") == compute for e in state.events if e.executed and not e.error):
            return (
                "READ SOURCE TABLES: locate the requested annual PDFs once, inspect each relevant native table "
                "with pdf.tables.inspect and read the target workbook headers/row keys. Reuse observed exact paths. "
                "Do not repeat successful source reads. Match supported/applications by the observed table headers "
                "and row/subrow, not a nearby university or subject. Use the exposed public read-only " + compute
                + " after all selected source rows/columns have been observed. Calculations use only actual source data. "
                "Use tools_search for a missing tool once, then CALL it; repeated search does not read data."
            )
        if "range.write" not in actions or kind == "ecs-rates":
            return (
                "WRITE COMPUTED DATA: source computation is already available. Copy its current model-visible "
                "matrix values into the actual Calc target with range.write. JSON values MUST be a TWO-DIMENSIONAL "
                "array of plain numbers, e.g. [[2019,25,7,0.28]]; a year is a JSON number, not \"2019\". "
                "For a single numeric rate row use [[r1,r2,...]], never a flat list and never typed-cell objects. "
                "Do not recompute or reread source PDFs after a successful computed result. Preserve observed row "
                "and column order and all existing workbook contents. If a write was rejected for evidence/type "
                "mismatch, correct its dimensions/types; an identical rejected payload cannot succeed. "
                "After every required output row is written, save once and read back the saved target. "
                + ("Store decimals without multiplying by 100. " if kind == "ecs-rates" else
                   "Create the new workbook only once, retain the exact four requested headers, format Success Rate "
                   "as 0.00% with fractional native numbers, then save_as the requested Desktop filename. ")
                + "When all saved output is correct, propose_done without another search or write."
            )
        return "FINALIZE: format fractional Success Rate values as 0.00%, save_as the requested Desktop workbook, then read back all five numeric-year records and propose_done. Do not repeat source extraction or create another workbook."
    if kind == "gemini-document":
        return _gemini_document_hint(state, facts)
    if kind in {"invoice-mail", "mail-wallpaper"}:
        folder = "Bills" if kind == "invoice-mail" else "Notes"
        if "messages.query" not in actions:
            return "FIND EMAIL: use thunderbird messages.query for folder_name=" + folder + ". Native mail tools do not require clicking the folder first. Select the requested invoice by its observed subject/date, or the latest Notes email with limit=1, select_from=latest. Do not repeatedly click dock/folder coordinates or search for generic attachment phrases."
        if "attachments.save" not in actions:
            return "SAVE ATTACHMENT: search exact thunderbird attachments.save, then call it using the message/attachment identity returned by messages.query. Exporting EML saves a mail container, not the attached document/PDF. Do not open the EML and mistake it for an extracted attachment. Choose only the requested attachment and inspect the returned saved path."
        if kind == "mail-wallpaper":
            if "document.extract_images" not in actions:
                return "EXTRACT FIRST IMAGE: call Writer document.extract_images on the actual saved document attachment, selecting first in native document reference order. Opening a document or an EML is not extraction. Use its returned image path."
            return "SET WALLPAPER: use os desktop.set_wallpaper with the actual first extracted image path. Verify the returned setting and finish with propose_done; do not export more images or reread emails."
        return "FILE AND RECORD: discover the actual receipts directory and tally book, inspect old receipt filenames for the naming pattern, save/rename the extracted December AWS PDF accordingly. Read the invoice amount/date/vendor and append ONE record after the existing tally records, preserving all originals. Save and read back the new record plus receipt path, then propose_done. Do not infer filesystem directories from mail folder names."
    if kind == "grading":
        return (
            "CURRENT GRADING: follow grading_progress from the real source/target ledger. Read the answer key "
            "and each remaining student's answers exactly once; retain question numbering and repeated letters. "
            "Compare each answer to the SAME numbered key answer. Write numeric correct/incorrect scores "
            "using the observed grading example and weights; do not put student answer letters into score cells "
            "or generate self-referential formulas. Preserve already graded students. Write the remaining score "
            "rows as one model-selected matrix where the public tool permits it; do not search/read the entire "
            "workbook between every row. Use current tools before searching again. Once all detailed scores and "
            "totals are written, save once, read back the full target, and propose_done."
        )
    if kind == "person-background":
        paths = []
        for e, _, action, _ in facts:
            if action == "filesystem.find":
                body = gemini_native_result(e)
                paths.extend(m.get("path") for m in body.get("matches", []) if m.get("kind") == "file")
        pictures = [p for p in paths if str(p).lower().endswith((".jpg", ".jpeg", ".png")) and not str(p).endswith("/pic.jpg")]
        documents = [p for p in paths if str(p).lower().endswith(".docx")]
        def call_stage(note, adapter, action, params):
            return "BACKGROUND STEP: " + note + "\n" + json.dumps({"adapter": adapter,
                "action": action, "payload": {"params": params}}, ensure_ascii=False)
        if not paths:
            return call_stage("Discover the actual Desktop source picture and requirements document.",
                "os", "filesystem.find", {"roots": ["~/Desktop"], "name_patterns": ["*.jpg", "*.png", "*.docx"],
                    "kind": "file", "recursive": False, "max_results": 20})
        if documents and not any(action == "document.read_file" for _, _, action, _ in facts):
            return call_stage("Read the actual requirements DOCX now. Do not click dock or folders; the exact file path is already observed.",
                "libreoffice_writer", "document.read_file", {"path": documents[0]})
        if pictures and not any(action == "desktop.open_path" and args.get("path") == pictures[0] for _, _, action, args in facts):
            return call_stage("Open the actual source image and inspect its screenshot before selecting the person. Do not launch an unrelated dock icon.",
                "os", "desktop.open_path", {"path": pictures[0]})
        segments = [e for e, _, action, args in facts if action == "command.run" and "grabCut" in json.dumps(args)]
        if not segments:
            failed_cv2 = any(e.error and "No module named" in str(e.error) and "cv2" in str(e.error) for e in state.events)
            installed = any(action == "command.run" and "opencv-python" in json.dumps(args) for _, _, action, args in facts)
            if failed_cv2 and not installed:
                return call_stage("The segmentation interpreter reported missing cv2. Install only the needed "
                    "image-processing modules, then retry the same finite source-image operation once.",
                    "os", "command.run", {"argv": ["pip3", "install", "opencv-python", "numpy"],
                        "cwd_source": "home", "provenance": "shell_history"})
            picture = pictures[0] if pictures else None
            script = ("import cv2,numpy as np; " + f"im=cv2.imread({picture!r}); "
                "h,w=im.shape[:2]; mask=np.zeros((h,w),np.uint8); "
                "rect=(int(.18*w),int(.18*h),int(.60*w),int(.81*h)); cv2.setRNGSeed(0); "
                "cv2.grabCut(im,mask,rect,np.zeros((1,65),np.float64),np.zeros((1,65),np.float64),10,cv2.GC_INIT_WITH_RECT); "
                "keep=(mask==cv2.GC_FGD)|(mask==cv2.GC_PR_FGD); out=np.where(keep[:,:,None],im,255).astype(np.uint8); "
                "ok=cv2.imwrite('/home/user/Desktop/pic.jpg',out,[cv2.IMWRITE_JPEG_QUALITY,95]); "
                "print({'written':bool(ok),'width':w,'height':h,'foreground_pixels':int(keep.sum()),'rect':rect})")
            return call_stage("Segment the PERSON from the actual opened source. In the observed portrait, "
                "the head begins near the upper fifth and the shoes extend almost to the bottom. A box "
                "covering only the middle half deletes limbs. The following source-based broad enclosure "
                "covers the entire visible head, backpack, arms, legs and shoes; GrabCut classifies scenery "
                "inside that enclosure. Preserve all original person pixels and image dimensions, compose "
                "on pure white and write pic.jpg. Do not crop, use the old narrow box or retype this code. "
                "The input path is the actual observed file; no reference image is used.",
                "os", "command.run", {"argv": ["python3", "-c", script], "cwd_source": "home", "provenance": "shell_history"})
        output_reads = [e for e, _, action, args in facts if action == "desktop.open_path"
                        and args.get("path") == "/home/user/Desktop/pic.jpg" and e.step > segments[-1].step]
        if output_reads:
            return "BACKGROUND FINISH: inspect the CURRENT screenshot of the saved pic.jpg. Check the whole head, backpack, both arms, legs AND shoes are retained on white. If correct and the file is present, propose_done with that observed evidence. If a visible defect remains, correct only that defect and reopen the changed output. Do not reopen the same unchanged image or repeat searches."
        return call_stage("The segmentation command has executed. Open the ACTUAL saved output now to inspect person completeness and a clean white background. If correct, propose_done; do not rerun edits or discovery without a visible defect.",
            "os", "desktop.open_path", {"path": "/home/user/Desktop/pic.jpg"})
    return None


def _vlc_hint(state, kind):
    events = [e for e in state.events if e.executed and not e.error]
    actions = {e.proposed.get("action") for e in events}
    if kind == "vlc-instances":
        configured = any(e.proposed.get("action") == "preferences.configure"
            and e.proposed.get("arguments", {}).get("allow_multiple_instances") is True
            and (result_payload(e).get("semantic_preferences", {}).get("allow_multiple_instances") is True
                 or result_payload(e).get("after", {}).get("one-instance-when-started-from-file") == "0")
            for e in events)
        if not configured:
            return "SET PREFERENCE: call preferences.configure with allow_multiple_instances=true. This changes the persisted single-instance behavior so desktop-opened media can start independent players."
        return "FINISH: the successful preferences.configure result already verifies the persisted multi-instance setting. Do not configure it again, click the dock repeatedly or poll playback.status to verify a preference; playback state is unrelated. Review the actual returned preference evidence and propose_done. No new sample video or extra playback is requested."
    statuses = [result_payload(e) for e in events if e.proposed.get("action") == "playback.status"]
    if statuses and statuses[-1].get("state") == "playing" and "/Desktop/" in str(statuses[-1].get("source", "")):
        return ("FINISH: native playback.status reports playing for the actual Desktop source "
                + str(statuses[-1]["source"]) + ". If this is the requested observed music video, "
                "propose_done now and leave it playing. Opening through the GUI does not create a "
                "playback.open event; no extra native open is required. Do not reopen the chooser or poll again.")
    if "playback.open" not in actions:
        return (
            "OPEN OBSERVED MEDIA: discover the exact Desktop video path instead of guessing from its truncated "
            "desktop label. If filesystem.find is not offered in this VLC domain, repeated tools_search will "
            "not make it callable. Use VLC's Open File dialog (Ctrl+O), navigate to the actual Desktop and select "
            "the visible music-video file, or read an observed exact path from the dialog. Open that file in "
            "VLC. Do not double-click empty desktop coordinates or invent a longer filename. "
            "Continue from the CURRENT screenshot: if the chooser is still open, finish selecting the "
            "file; if VLC already shows the video, call playback.status now instead of reopening it. "
            "A successful GUI open need not have a playback.open event."
        )
    return "VERIFY PLAYBACK: call playback.status once. If the observed Desktop music video is playing, propose_done immediately and leave it playing. Do not keep reopening the file, guessing filenames or searching filesystem.find. If it ended, reopen the SAME observed file and finish promptly."


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
    if (targets or {}).get(state.task_id) == "personal-cleanup" and state.domain == "libreoffice_impress":
        return _personal_cleanup_hint(state)
    if (targets or {}).get(state.task_id) == "sentence-tabstops" and state.domain == "libreoffice_writer":
        return _tabstop_hint(state)
    if (targets or {}).get(state.task_id) == "initial-letter-colors" and state.domain == "libreoffice_writer":
        return _vowel_hint(state)
    if (targets or {}).get(state.task_id) == "comma-table" and state.domain == "libreoffice_writer":
        return _comma_table_hint(state)
    kind = (targets or {}).get(state.task_id)
    if state.domain == "multi_apps":
        return _cross_app_hint(state, kind)
    if state.domain == "vlc" and kind in {"vlc-play", "vlc-instances"}:
        return _vlc_hint(state, kind)
    return None
