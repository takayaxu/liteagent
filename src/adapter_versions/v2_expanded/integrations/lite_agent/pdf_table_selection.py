"""Read-only selection and arithmetic over model-selected PDF table evidence."""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import Any

from . import batch_table_semantics as batches

TOOL_NAME = "pdf_table_records_compute"
ACTION = "table.records.compute"


def requested_headers(state: Any) -> list[str]:
    """Read an explicitly quoted header list from the public instruction."""
    instruction = str(getattr(state, "instruction", ""))
    match = re.search(r"(?i)\bheaders?\s+(.+?)(?:[.;\n]|$)", instruction)
    return re.findall(r'["“]([^"”\n]+)["”]', match.group(1)) if match else []


def active(state: Any) -> bool:
    return (
        getattr(state, "domain", None) == "multi_apps"
        and batches.requires_structured_pdf_table_observation(state)
        and batches.requests_new_workbook(state)
    )


def observations(state: Any) -> dict[int, dict[str, Any]]:
    result = {}
    for event in getattr(state, "events", ()):
        if not getattr(event, "executed", False) or not batches._event_matches_action(event, state, "pdf.tables.inspect"):
            continue
        for mapping in batches._nested_mappings(event.result):
            if isinstance(mapping.get("rows"), list) and mapping.get("input_path"):
                result[event.step] = mapping
                break
    return result


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def header_paths(observation: dict[str, Any]) -> dict[str, int]:
    """Build hierarchical labels from explicit merged header spans."""
    rows = observation["rows"]
    offset = observation.get("row_offset", 0)
    merges = observation.get("merged_cells", [])
    if offset != 0:
        raise ValueError("source evidence must include header rows starting at row_offset=0")
    # Model selects the exact hierarchical header; no institution/measure defaults.
    paths = {}
    for column in range(observation.get("column_count", len(rows[0]))):
        parts = []
        for row_index, row in enumerate(rows):
            if any(re.fullmatch(r"[+-]?[\d,]+(?:\.\d+)?%?", line.strip()) for cell in row if isinstance(cell, str) for line in cell.splitlines()):
                break
            value = row[column] if column < len(row) else None
            if value is None:
                for merged in merges:
                    r, c, rs, cs = (
                        [merged[k] for k in ("row", "column", "row_span", "column_span")]
                        if isinstance(merged, dict) else merged
                    )
                    if r <= row_index < r + rs and c <= column < c + cs:
                        value = rows[r][c]
                        break
            if value and (not parts or _normalized(parts[-1]) != _normalized(value)):
                parts.append(re.sub(r"\s+", " ", str(value)).strip())
        path = " / ".join(parts)
        if path in paths:
            paths[path] = -1  # Ambiguous labels cannot select a column.
        else:
            paths[path] = column
    return paths


def requested_column_group(state: Any, columns: list[str]) -> str | None:
    """Match an explicit hierarchical header group as a whole instruction token."""
    instruction = str(getattr(state, "instruction", ""))
    groups = {path.split(" / ", 1)[0] for path in columns if " / " in path}
    mentioned = [group for group in groups if re.search(r"(?<!\w)" + re.escape(group) + r"(?!\w)", instruction, re.IGNORECASE)]
    return mentioned[0] if len(mentioned) == 1 else None


def tool(state: Any) -> dict[str, Any]:
    observed = observations(state)
    summaries = []
    for step, observation in observed.items():
        labels = [
            {"row_index": row["row_index"], "subrow_index": row["subrow_index"], "label": row["values"][0]}
            for row in observation.get("aligned_rows", []) if not row.get("ambiguous")
        ]
        summaries.append({"observation_step": step, "input_path": observation["input_path"], "subrows": labels})
    paths = sorted({observation["input_path"] for observation in observed.values()})
    columns = sorted(set().union(*(header_paths(observation) for observation in observed.values()))) if observed else []
    group = requested_column_group(state, columns)
    if group:
        columns = [path for path in columns if path.split(" / ", 1)[0] == group]
    string = {"type": "string", "minLength": 1}
    # Standard JSON Schema cannot compare arbitrary sibling string values.
    # Express known header conflicts before execution using instruction text
    # and model proposals; runtime validation covers all other strings.
    header_candidates = set(re.findall(r'["“]([^"”\n]+)["”]', str(getattr(state, "instruction", ""))))
    for event in getattr(state, "events", ()):
        args = event.proposed.get("arguments", {})
        if event.proposed.get("action") == ACTION and isinstance(args.get("key_header"), str):
            header_candidates.add(args["key_header"])
    header_constraints = [
        {
            "if": {"properties": {"key_header": {"const": header}}, "required": ["key_header"]},
            "then": {"properties": {"fields": {"items": {"properties": {"name": {"not": {"const": header}}}}}}},
        }
        for header in sorted(header_candidates)
    ]
    requested = requested_headers(state)
    field_names = requested[1:-1] if requested and re.search(r"(?i)rate|ratio|percent", requested[-1]) else requested[1:]
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Read-only: select one record per discovered PDF from explicit observed table "
                "coordinates and optionally compute a ratio. Choose the requested subject yourself "
                "from aligned subrow labels; the runner does not choose a subject, institution, "
                "year, output header or sort order. Specify sources in your desired output order. "
                "The first column is generated once from key_header and sources[].key. "
                "fields contains only additional numeric columns; never repeat key_header there. "
                "key_evidence is a literal filename fragment supporting the output identifier, "
                "not the selected subject or cell text. Correct a rejected field only; preserve "
                "unrelated source selections, output keys, fields and ratio. "
                "Select fields by the exact observed hierarchical header_path. Ratios are fractions "
                "(not multiplied by 100). When the user requests percentages with decimal places, "
                "that specifies the final display, not a string storage type. Write the computed "
                "unrounded numeric fractions, then explicitly apply range.format using the "
                "instruction-derived display_contract returned by this computation. "
                "This does not create, write, format or save any workbook. "
                f"Observed source choices: {summaries!r}. Header paths: {columns!r}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key_header": {**string, **({"enum": requested[:1]} if requested else {}), "description": "Header of the first output column, generated exactly once from sources[].key. Use the user's exact requested spelling. Do not declare this header again in fields[].name."},
                    "row_label": {**string, "description": "Requested subject label matched against the selected observed subrow. This is independent of filename evidence."},
                    "sources": {
                        "type": "array", "minItems": len(paths) or 1, "maxItems": len(paths) or 100,
                        "items": {
                            "type": "object",
                            "properties": {
                                "observation_step": {"type": "integer", "enum": sorted(observed)},
                                "input_path": {"type": "string", "enum": paths},
                                "row_index": {"type": "integer", "minimum": 0},
                                "subrow_index": {"type": "integer", "minimum": 0},
                                "key": {"type": ["string", "number"], "description": "Value of the first output column named key_header, such as the requested full year. Keep this output value when correcting key_evidence."},
                                "key_evidence": {**string, "description": "Literal nonempty substring of this source's filename supporting key. This is filename evidence only, never a subject label, table header or cell text. For report31.pdf and key=2031, use '31' or 'report31'; keep key=2031. A rejection of this field requires changing only key_evidence."},
                            },
                            "required": ["observation_step", "input_path", "row_index", "subrow_index", "key", "key_evidence"],
                            "additionalProperties": False,
                        },
                    },
                    "fields": {
                        "type": "array", "minItems": 1,
                        "description": "Additional numeric columns only. The first column already comes from sources[].key; fields[].name must differ from key_header. Do not select a subject-label column as a year field.",
                        "items": {
                            "type": "object",
                            "properties": {"name": {**string, **({"enum": field_names} if field_names else {}), "description": "Exact user-requested output header for this numeric field, not the source header. Must differ from key_header and all other output headers."}, "header_path": {"type": "string", "enum": columns}},
                            "required": ["name", "header_path"], "additionalProperties": False,
                        },
                    },
                    "ratio": {
                        "type": "object",
                        "properties": {
                            "name": {**string, "description": "Exact requested output header for the computed ratio; independent of source table labels."},
                            "numerator": {**string, "description": "Name of the numerator in fields[].name; update this reference when renaming that output field."},
                            "denominator": {**string, "description": "Name of the denominator in fields[].name; update this reference when renaming that output field."},
                        },
                        "required": ["name", "numerator", "denominator"], "additionalProperties": False,
                    },
                },
                "required": ["key_header", "row_label", "sources", "fields"],
                "additionalProperties": False,
                **({"allOf": header_constraints} if header_constraints else {}),
            },
        },
    }


def compute(state: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    observed = observations(state)
    sources = arguments["sources"]
    expected_paths = set(batches._observed_pdf_source_paths(state))
    paths = [source["input_path"] for source in sources]
    if len(paths) != len(set(paths)) or set(paths) != expected_paths:
        raise ValueError("source evidence requires exactly one record per discovered PDF; duplicates or omissions are invalid")
    fields = arguments["fields"]
    columns = sorted({path for observation in observed.values() for path in header_paths(observation)})
    group = requested_column_group(state, columns)
    if group and any(field["header_path"].split(" / ", 1)[0] != group for field in fields):
        raise ValueError(f"selected header_path must use the explicitly requested observed column group {group!r}; correct only fields[].header_path, preserving output headers, source rows and ratio")
    for index, field in enumerate(fields):
        if field["name"] == arguments["key_header"]:
            raise ValueError(
                f"fields[{index}].name duplicates key_header={arguments['key_header']!r}. "
                "The first column already uses sources[].key. Remove only this duplicate "
                "field; preserve source keys, evidence, other fields and ratio. No computation executed."
            )
    headers = [arguments["key_header"], *(field["name"] for field in fields)]
    ratio = arguments.get("ratio")
    if ratio:
        headers.append(ratio["name"])
    requested = requested_headers(state)
    if requested and headers != requested:
        raise ValueError(f"output headers must match the instruction's exact order and spelling: {requested!r}; change key_header/fields[].name/ratio.name and corresponding numerator/denominator name references, retaining source selectors and numeric inputs")
    if len(headers) != len(set(headers)):
        raise ValueError("output headers must be distinct model-selected strings")
    values, provenance = [], []
    for source in sources:
        observation = observed.get(source["observation_step"])
        if observation is None or observation["input_path"] != source["input_path"]:
            raise ValueError("source evidence observation_step and input_path do not match")
        if source["key_evidence"] not in PurePosixPath(source["input_path"]).name:
            raise ValueError(
                f"sources[{sources.index(source)}].key_evidence={source['key_evidence']!r} "
                f"must be a literal substring of filename={PurePosixPath(source['input_path']).name!r}. "
                f"Keep key={source['key']!r} and all other selections; change only key_evidence "
                "to the filename fragment supporting that key. No computation executed."
            )
        matches = [
            row for row in observation.get("aligned_rows", [])
            if row.get("row_index") == source["row_index"] and row.get("subrow_index") == source["subrow_index"]
            and not row.get("ambiguous")
        ]
        if len(matches) != 1:
            raise ValueError("source evidence lacks a unique aligned subrow; inspect the table again")
        selected = matches[0]
        if _normalized(arguments["row_label"]) not in _normalized(selected["values"][0]):
            raise ValueError(f"source evidence row_label does not match selected subrow: {selected['values'][0]!r}")
        columns = header_paths(observation)
        record = {}
        citations = []
        for field in fields:
            column = columns.get(field["header_path"], -1)
            if column < 0:
                raise ValueError(f"source evidence header_path is missing or ambiguous: {field['header_path']!r}")
            raw = selected["values"][column]
            if not isinstance(raw, str) or not re.fullmatch(r"[+-]?[\d,]+(?:\.\d+)?", raw.strip()):
                raise ValueError(f"source evidence selected cell is not a single numeric value: {raw!r}")
            number = float(raw.replace(",", ""))
            if not math.isfinite(number):
                raise ValueError("source evidence contains a non-finite number")
            record[field["name"]] = int(number) if number.is_integer() else number
            citations.append({"field": field["name"], "column": column, "raw": raw, "header_path": field["header_path"]})
        row = [source["key"], *(record[field["name"]] for field in fields)]
        if ratio:
            if ratio["numerator"] not in record or ratio["denominator"] not in record:
                raise ValueError("ratio numerator and denominator must name selected fields")
            denominator = record[ratio["denominator"]]
            if denominator == 0:
                raise ValueError("ratio denominator is zero; explicitly select a supported alternative")
            row.append(record[ratio["numerator"]] / denominator)
        values.append(row)
        provenance.append({**source, "observed_label": selected["values"][0], "cells": citations})
    result = {"status": "ok", "executed": True, "headers": headers, "values": values, "provenance": provenance, "ratio": ratio}
    if ratio:
        contract = percentage_display_contract(state, result)
        if contract:
            result["display_contract"] = contract
            result["next_step_hint"] = percentage_guidance(contract)
    return result


def latest_result(state: Any) -> dict[str, Any] | None:
    for event in reversed(getattr(state, "events", ())):
        if getattr(event, "executed", False) and event.proposed.get("action") == ACTION:
            return event.result
    return None


def allowed_routes(state: Any) -> set[tuple[str, str]]:
    """Operation eligibility, shared by schema, search results and execution."""
    if batches.structured_pdf_source_discovery_pending(state):
        return {("os", "filesystem.find")}
    if not batches.native_pdf_table_observation_complete(state):
        return {("os", "pdf.tables.inspect")}
    created = batches._current_create_events(state)
    if not created:
        return {("libreoffice_calc", "workbook.create_new")} if latest_result(state) else set()
    result = latest_result(state)
    if result is None:
        return set()
    matrix = [result["headers"], *result["values"]] if result else []
    writes = [event for event in state.events if event.executed and event.step > created[-1].step and batches._event_matches_action(event, state, "range.write")]
    written = []
    for event in writes:
        written.extend(batches._batch_arguments(event, state).get("values", []))
    if not writes or not all(any(_equal_row(actual, row) for actual in written) for row in matrix):
        return {("libreoffice_calc", "range.write")}
    target = percentage_format_target(state)
    formats = [event for event in state.events if event.executed and event.step > writes[-1].step and batches._event_matches_action(event, state, "range.format") and not format_errors(state, batches._batch_arguments(event, state))]
    if target and not formats:
        return {("libreoffice_calc", "range.format")}
    last_change = max([event.step for event in writes + formats])
    saves = [event for event in state.events if event.executed and event.step > last_change and any(batches._event_matches_action(event, state, action) for action in ("workbook.save", "workbook.save_as"))]
    if not saves:
        return {("libreoffice_calc", "workbook.save_as")}
    if completion_errors(state):
        return {("libreoffice_calc", "range.read")}
    return {("libreoffice_calc", "workbook.inspect")}


def percentage_display_contract(state: Any, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Separate the instruction's display requirement from numeric storage."""
    result = result if result is not None else latest_result(state)
    instruction = str(getattr(state, "instruction", ""))
    requirement = re.search(r"(?i)percent(?:age)?(?:\s+form)?|%", instruction)
    if not result or not result.get("ratio") or not requirement:
        return None
    match = re.search(r"(?i)\b(\d+)\s+decimal\s+places?", instruction)
    decimals = int(match.group(1)) if match else 2
    return {
        "instruction_evidence": [requirement.group(0), *([match.group(0)] if match else [])],
        "decimal_places": decimals,
        "decimal_places_source": "instruction" if match else "adapter_default",
        "number_format": "0" + ("." + "0" * decimals if decimals else "") + "%",
        "numeric_values": [row[-1] for row in result["values"]],
        "expected_display": [f"{row[-1] * 100:.{decimals}f}%" for row in result["values"]],
    }


def percentage_guidance(contract: dict[str, Any]) -> str:
    return (
        f"According to the user instruction {contract['instruction_evidence']!r}, "
        f"the required percentage display is {contract['expected_display']!r}. "
        "This is a display requirement; the instruction does not specify a storage type or Calc format code. "
        f"This numeric table API implements it by writing the unrounded fractions {contract['numeric_values']!r} "
        f"as numbers, then explicitly calling range.format with number_format={contract['number_format']!r}. "
        "Percentage strings can be correct display text but are not numeric values accepted by range.write here."
    )


def percentage_format_target(state: Any) -> dict[str, Any] | None:
    """Describe a separate format action from instruction and model-written origin."""
    result = latest_result(state)
    contract = percentage_display_contract(state, result)
    if not contract:
        return None
    number_format = contract["number_format"]
    creates = batches._current_create_events(state)
    for event in getattr(state, "events", ()):
        if not event.executed or (creates and event.step <= creates[-1].step) or not batches._event_matches_action(event, state, "range.write"):
            continue
        params = batches._batch_arguments(event, state)
        values = params.get("values", [])
        geometry = batches.a1_geometry(str(params.get("range", "")))
        if values and geometry and _equal_row(values[0], result["headers"]):
            column = batches.column_label(batches.column_number(geometry[0]) + len(result["headers"]) - 1)
            return {"sheet": params.get("sheet"), "range": f"{column}{geometry[1] + 1}:{column}{geometry[1] + len(result['values'])}", "format": {"number_format": number_format}}
    return None


def format_errors(state: Any, params: dict[str, Any]) -> list[str]:
    target = percentage_format_target(state)
    if target and (params.get("sheet") != target["sheet"] or params.get("range") != target["range"] or params.get("format", {}).get("number_format") != target["format"]["number_format"]):
        return [f"percentage display requires explicit range.format parameters {target!r}; preserve the computed fractions, do not round or rewrite their values. No mutation executed."]
    return []


def stage_hint(state: Any) -> str:
    routes = sorted(allowed_routes(state))
    hint = f"Next eligible operation (search it first if undiscovered): {routes!r}."
    contract = percentage_display_contract(state)
    if contract:
        hint += " " + percentage_guidance(contract)
    target = percentage_format_target(state)
    if routes == [("libreoffice_calc", "range.format")] and target:
        hint += f" The complete computed table has already been written successfully. Do not repeat range.write or save yet. Search libreoffice_calc.range.format and execute it using {target!r}. Numeric fractions stay unchanged."
    elif routes == [("libreoffice_calc", "range.read")] and target:
        result = latest_result(state)
        geometry = batches.a1_geometry(target["range"])
        column = batches.column_label(batches.column_number(geometry[0]) - len(result["headers"]) + 1)
        hint += f" Read back the full table on sheet {target['sheet']!r}, range {column}{geometry[1] - 1}:{geometry[2]}{geometry[3]}, including display_text."
    return hint


def write_errors(state: Any, params: dict[str, Any]) -> list[str]:
    result = latest_result(state)
    if result is None:
        return ["source evidence must be explicitly selected and calculated before writing records"]
    matrix = [result["headers"], *result["values"]]
    values = params.get("values")
    if not isinstance(values, list) or not values:
        return ["source evidence write requires a nonempty explicit values matrix"]
    geometry = batches.a1_geometry(str(params.get("range", "")))
    if geometry is None:
        return ["source evidence requires an explicit rectangular destination range"]
    first_column, first_row, last_column, last_row = geometry
    if batches.column_number(last_column) - batches.column_number(first_column) + 1 != len(matrix[0]) or last_row - first_row + 1 != len(values):
        contract = percentage_display_contract(state)
        return ["source evidence destination rectangle does not match submitted matrix dimensions. " + (percentage_guidance(contract) if contract else "Preserve the computed numeric values.")]
    created = batches._current_create_events(state)
    previous = [event for event in getattr(state, "events", ()) if getattr(event, "executed", False) and batches._event_matches_action(event, state, "range.write") and (not created or event.step > created[-1].step)]
    origin = None
    for event in previous:
        old = batches._batch_arguments(event, state)
        old_geometry = batches.a1_geometry(str(old.get("range", "")))
        if old.get("values") and _equal_row(old["values"][0], matrix[0]) and old_geometry:
            origin = (old.get("sheet"), old_geometry[0], old_geometry[1])
            break
    for offset in range(len(matrix) - len(values) + 1):
        expected = matrix[offset:offset + len(values)]
        if all(_equal_row(actual, wanted) for actual, wanted in zip(values, expected)):
            if origin and (params.get("sheet"), first_column, first_row - offset) != origin:
                return ["source evidence destination is inconsistent with the previously written header origin"]
            if not origin and offset != 0:
                return ["write the selected header first (or include it with all data) to establish the output origin"]
            return []
    contract = percentage_display_contract(state)
    return ["source evidence mismatch: submitted values must match contiguous rows of the model-selected computation; "
            f"submitted={values!r}; computed_headers={result['headers']!r}; computed_rows={result['values']!r}; "
            + (percentage_guidance(contract) + " " if contract else "") +
            "correct your original range.write parameters; no mutation was executed"]


def _equal_row(actual: Any, wanted: list[Any]) -> bool:
    if not isinstance(actual, list) or len(actual) != len(wanted):
        return False
    for value, expected in zip(actual, wanted):
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value - expected) > 1e-10:
                return False
        elif value != expected:
            return False
    return True


def completion_errors(state: Any) -> list[str]:
    result = latest_result(state)
    if result is None:
        return ["select and compute source records before completion"]
    creates = batches._current_create_events(state)
    if not creates:
        return ["create the requested workbook before completion"]
    writes = [event for event in getattr(state, "events", ()) if getattr(event, "executed", False) and event.step > creates[-1].step and batches._event_matches_action(event, state, "range.write")]
    if not writes:
        return ["write the selected records before completion"]
    mutations = writes + [event for event in getattr(state, "events", ()) if getattr(event, "executed", False) and event.step > creates[-1].step and batches._event_matches_action(event, state, "range.format")]
    last_change = max(event.step for event in mutations)
    saves = [event for event in getattr(state, "events", ()) if getattr(event, "executed", False) and event.step > last_change and any(batches._event_matches_action(event, state, action) for action in ("workbook.save", "workbook.save_as"))]
    if not saves:
        return ["explicitly save the workbook after the final write and format"]
    matrix = [result["headers"], *result["values"]]
    for event in reversed(getattr(state, "events", ())):
        if not getattr(event, "executed", False) or event.step <= saves[-1].step or not batches._event_matches_action(event, state, "range.read"):
            continue
        for mapping in batches._nested_mappings(event.result):
            values = mapping.get("values")
            if isinstance(values, list) and len(values) == len(matrix) and all(_equal_row(actual, expected) for actual, expected in zip(values, matrix)):
                target = percentage_format_target(state)
                if target:
                    display = mapping.get("display_text")
                    decimals = target["format"]["number_format"].count("0") - 1
                    expected_display = [f"{row[-1] * 100:.{decimals}f}%" for row in result["values"]]
                    if not isinstance(display, list) or len(display) != len(matrix) or any(not row for row in display) or [str(row[-1]) for row in display[1:]] != expected_display:
                        return [f"read back the requested percentage display after saving; expected={expected_display!r}"]
                return []
    return ["after saving, range.read the complete written table and verify numeric values and display formatting"]


def complete(state: Any) -> bool:
    return not completion_errors(state)
