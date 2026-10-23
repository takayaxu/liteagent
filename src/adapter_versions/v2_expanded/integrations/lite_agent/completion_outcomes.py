"""Completion evidence from observed objects, never from operation counts.

Issues are a shared contract for the gate, model context and recovery surface.
Checks consume instruction text and native Adapter results only. They neither
execute repairs nor manufacture model arguments. Unsupported instruction
semantics continue through the existing semantic checks and model review.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .completion_policy import (
    action_is_read_only,
    action_is_save,
    effective_canonical_action,
)
from .instruction_semantics import (
    requested_chart_count,
    requested_pivot_count,
    requested_sheet_names,
)


def result_payload(event: Any) -> dict[str, Any]:
    """Prefer full native evidence over the bounded model-context projection."""
    result = event.result
    if not isinstance(result, dict):
        return {}
    response = result.get("adapter_response")
    if isinstance(response, dict) and isinstance(response.get("result"), dict):
        if not response.get("truncated"):
            return response["result"]
        # AdapterExecutor can compact the raw envelope while retaining a
        # larger purpose-built cell/object hint. A raw summary is not fuller
        # evidence merely because it is under adapter_response.result.
        if isinstance(result.get("context_hint"), dict):
            return result["context_hint"]
        return {**response["result"], "context_truncated": True}
    for key in ("result", "context_hint"):
        if isinstance(result.get(key), dict):
            return result[key]
    return result


def _events(state: Any) -> list[tuple[Any, str, dict[str, Any], dict[str, Any]]]:
    events = []
    for event in state.events:
        kind = event.proposed.get("kind")
        if kind == "gui":
            if event.executed or event.validated:
                events.append((event, "gui", {}, {}))
            continue
        if kind != "adapter":
            # Searches, audits and successful completion claims change no file.
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        if not event.executed or getattr(event, "error", None):
            if domain == "libreoffice_calc" and event.validated and not action_is_read_only(action):
                # A dispatched replacement can remove the old object before
                # failing. Never reuse a snapshot from before that attempt.
                events.append((event, "uncertain:" + action, args, {}))
            continue
        # Opening another workbook invalidates evidence from the previous file.
        if domain == "libreoffice_calc" and action in {"workbook.open", "workbook.create_new"}:
            events = []
        if domain == "libreoffice_calc":
            events.append((event, action, args, result_payload(event)))
    return events


def _issue(code: str, target: Any, expected: Any, observed: Any, *,
           actions: tuple[str, ...], step: int | None = None,
           mismatch: bool = False) -> dict[str, Any]:
    return {
        "code": code,
        "kind": "state_mismatch" if mismatch else "missing_observation",
        "target": target,
        "expected": expected,
        "observed": observed,
        "evidence_step": step,
        "repair_actions": list(actions),
        "message": f"{code}: {target}; required {expected!r}; observed {observed!r}",
    }


def _alias(value: Any) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split()
    return " ".join(w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words)


def _independent_sums(instruction: str, count: int) -> dict[str, Any] | None:
    """Recognize explicit independent group totals; leave cross-tabs to review."""
    match = re.search(
        r"\b(?:total|sum\s+of)\s+(.+?)\s+(?:for|by)\s+each\s+(.+?)(?:[.!?]|$)",
        instruction, re.I,
    )
    if not match or re.search(
        r"\b(?:cross.?tab|percentage|percent|versus|against|combination)\b", instruction, re.I
    ):
        return None
    groups = [s.strip(" \"'") for s in re.split(r"\s*,\s*|\s+and\s+", match[2], flags=re.I) if s.strip()]
    if len(groups) != count or len(set(map(_alias, groups))) != count:
        return None
    return {"groups": groups, "measure": match[1].strip()}


def rectangle(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\$?([A-Za-z]+)\$?([1-9]\d*)(?::\$?([A-Za-z]+)\$?([1-9]\d*))?", value)
    if not match:
        return None

    def column(word: str) -> int:
        number = 0
        for char in word.upper():
            number = number * 26 + ord(char) - 64
        return number

    rect = (column(match[1]), int(match[2]), column(match[3] or match[1]), int(match[4] or match[2]))
    return rect if rect[0] <= rect[2] and rect[1] <= rect[3] else None


def _overlap(a: Any, b: Any) -> bool:
    return bool(a and b and a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3])


def _complete_rows(payload: dict[str, Any], rect: Any) -> list | None:
    rows = payload.get("display_text")
    if (not rect or payload.get("truncated") or payload.get("context_truncated")
            or not isinstance(rows, list) or len(rows) != rect[3] - rect[1] + 1
            or any(not isinstance(row, list) or len(row) != rect[2] - rect[0] + 1 for row in rows)):
        return None
    return rows


def _same_document(events: list, event: Any, payload: dict) -> bool:
    inspections = [(e, p.get("url")) for e, a, _, p in events if a == "workbook.inspect" and p.get("url")]
    current_url = inspections[-1][1] if inspections else None
    preceding = [url for e, url in inspections if e.step < event.step]
    read_url = payload.get("workbook_url") or (preceding[-1] if preceding else None)
    return not (current_url and read_url and current_url != read_url)


def _used_rectangle(sheet: dict) -> Any:
    if rect := rectangle(sheet.get("used_range_a1")):
        return rect
    used = sheet.get("used_range")
    if isinstance(used, dict) and all(k in used for k in ("start_column", "start_row", "end_column", "end_row")):
        return tuple(int(used[k]) + 1 for k in ("start_column", "start_row", "end_column", "end_row"))
    return None


def _complete_source_range(events: list, sheet_name: str, rect: Any) -> bool:
    # The full returned rectangle may still be only a header or a sample of
    # the dataset. Bind its extent to a native observation, not to its own args.
    for _, action, _, payload in reversed(events):
        if action != "workbook.inspect":
            continue
        sheet = next((s for s in payload.get("sheets", []) if s.get("name") == sheet_name), None)
        if sheet and (used := _used_rectangle(sheet)):
            return rect == used
    sources = {rectangle(p.get("source_range")) for _, a, _, h in events if a == "workbook.inspect"
               for s in h.get("sheets", []) for p in s.get("pivot_tables", [])
               if p.get("source_sheet") == sheet_name}
    return rect in sources - {None}


def _source(events: list, spec: dict) -> dict | None:
    for event, action, args, payload in reversed(events):
        if action != "range.read" or not _same_document(events, event, payload):
            continue
        if payload.get("sheet", args.get("sheet")) != args.get("sheet"):
            continue
        if rectangle(payload.get("range", args.get("range"))) != rectangle(args.get("range")):
            continue
        rect = rectangle(args.get("range"))
        rows = _complete_rows(payload, rect)
        if not rows or len(rows) < 2 or not _complete_source_range(events, args.get("sheet"), rect):
            continue
        headers = rows[0]

        def resolve(words: str) -> Any:
            hits = [h for h in headers if _alias(h) == _alias(words)]
            return hits[0] if len(hits) == 1 else None

        groups = [resolve(g) for g in spec["groups"]]
        measure = resolve(spec["measure"])
        if not all(groups) or not measure:
            continue
        # A read predating edits to its source cannot establish expected totals.
        if any(e.step > event.step and not action_is_read_only(a)
               and not action_is_save(a) and (a == "gui" or ar.get("sheet") == args.get("sheet"))
               for e, a, ar, _ in events):
            continue
        totals = {}
        try:
            mi = headers.index(measure)
            for group in groups:
                gi = headers.index(group)
                values: dict[str, float] = {}
                for index, row in enumerate(rows[1:], 1):
                    category = str(row[gi])
                    kinds = payload.get("kinds")
                    if kinds and kinds[index][mi] not in {"number", "formula"}:
                        raise ValueError("measure is not a native number")
                    native_values = payload.get("values")
                    value = _number(native_values[index][mi] if native_values else row[mi])
                    if not category:
                        raise ValueError("blank category")
                    values[category] = values.get(category, 0.0) + value
                totals[group] = values
        except (ValueError, TypeError, IndexError):
            continue
        return {"sheet": args.get("sheet"), "range": args.get("range"),
                "groups": groups, "measure": measure, "totals": totals, "step": event.step}
    return None


def _number(value: Any) -> float:
    # Only unambiguous numeric display strings; unknown locale needs observation.
    number = float(str(value).replace(",", "").replace("$", ""))
    if not math.isfinite(number):
        raise ValueError("non-finite value")
    return number


def _definition(pivot: dict) -> dict:
    return {key: pivot.get(key) for key in (
        "row_fields", "column_fields", "page_fields", "data_fields", "source_sheet", "source_range"
    )}


def _valid_definition(pivot: dict, group: str, source: dict) -> bool:
    fields = pivot.get("data_fields")
    return bool(
        pivot.get("row_fields") == [group]
        and pivot.get("column_fields") == [] and pivot.get("page_fields") == []
        and isinstance(fields, list) and len(fields) == 1
        and fields[0].get("field") == source["measure"]
        and str(fields[0].get("aggregation", "")).casefold() == "sum"
        and str(fields[0].get("show_data_as", "none")).casefold() == "none"
        and pivot.get("source_sheet") == source["sheet"]
        and rectangle(pivot.get("source_range")) == rectangle(source["range"])
    )


def _output_issue(events: list, sheet: str, pivot: dict, totals: dict, after: int) -> dict | None:
    target = {"sheet": sheet, "name": pivot.get("name"), "range": pivot.get("output_range")}
    rect = rectangle(pivot.get("output_range"))
    for event, action, args, payload in reversed(events):
        if (event.step <= after or action != "range.read" or args.get("sheet") != sheet
                or not _same_document(events, event, payload)):
            continue
        read_rect = rectangle(args.get("range"))
        rows = _complete_rows(payload, read_rect)
        if (payload.get("sheet", sheet) != sheet
                or rectangle(payload.get("range", args.get("range"))) != read_rect):
            continue
        # A containing sheet read is valid; an unrelated/partial read is not.
        if not rows or not rect or not (read_rect[0] <= rect[0] and read_rect[1] <= rect[1]
                                       and read_rect[2] >= rect[2] and read_rect[3] >= rect[3]):
            continue
        rows = [row[rect[0] - read_rect[0]:rect[2] - read_rect[0] + 1]
                for row in rows[rect[1] - read_rect[1]:rect[3] - read_rect[1] + 1]]
        observed = {}
        grand_totals = []
        try:
            if not rows or any(len(row) != 2 for row in rows):
                raise ValueError("expected a label and a sum column")
            for row in rows[1:]:
                key, value = str(row[0]), _number(row[1])
                if key in totals:
                    if key in observed:
                        raise ValueError(f"duplicate category {key}")
                    observed[key] = value
                else:
                    grand_totals.append({"label": key, "value": value})
            missing = sorted(totals.keys() - observed.keys())
            wrong = {k: {"expected": v, "observed": observed[k]}
                     for k, v in totals.items() if k in observed
                     and not math.isclose(v, observed[k], rel_tol=1e-9, abs_tol=0.011)}
            if (not missing and not wrong and len(grand_totals) == 1
                    and math.isclose(grand_totals[0]["value"], sum(totals.values()),
                                     rel_tol=1e-9, abs_tol=0.011)):
                return None
            observed = {"missing_categories": missing, "wrong_sums": wrong, "other_rows": grand_totals}
        except (ValueError, TypeError) as exc:
            observed = {"read_error": str(exc)}
        return _issue("pivot.output_mismatch", target, "one correct sum per source category and grand total",
                      observed, step=event.step, mismatch=True,
                      actions=("pivot.create", "range.read", "workbook.inspect", "workbook.save"))
    return _issue("pivot.output_unverified", target, "complete cell read after final mutation and save", None,
                  actions=("range.read", "workbook.inspect", "workbook.save"))


def completion_outcome_issues(state: Any) -> list[dict[str, Any]]:
    """Return live defects, distinguishing wrong state from absent evidence."""
    if getattr(state, "domain", None) == "os":
        from .filesystem_permission_semantics import outcome_issues

        return outcome_issues(state, result_payload, _issue)
    if getattr(state, "domain", None) != "libreoffice_calc":
        return []
    from .calc_scaled_outcomes import scaled_display_issues

    from .calc_formula_contract import outcome_issues as calculation_issues

    scaled_issues = [*scaled_display_issues(state), *calculation_issues(state)]
    instruction = str(state.instruction)
    counts = {"pivot_tables": requested_pivot_count(instruction), "charts": requested_chart_count(instruction)}
    counts = {key: value for key, value in counts.items() if value}
    if not counts:
        return scaled_issues
    events = _events(state)
    mutations = [(e, a, ar, p) for e, a, ar, p in events
                 if a == "gui" or (not action_is_read_only(a) and not action_is_save(a))]
    # Before any work, normal discovery owns the surface. Completion still
    # needs the existing action/persistence checks in that phase.
    if not mutations:
        return scaled_issues
    after = max([e.step for e, _, _, _ in mutations]
                + [e.step for e, a, _, _ in events if action_is_save(a)])
    inspections = [(e, p) for e, a, _, p in events if a == "workbook.inspect"]
    inspect_event, snapshot = inspections[-1] if inspections else (None, {})
    issues = list(scaled_issues)
    actions = tuple(dict.fromkeys([
        "workbook.inspect", "range.read", "sheet.create", "workbook.save",
        *("pivot.create" if k == "pivot_tables" else "chart.create" for k in counts),
    ]))
    if inspect_event is None or inspect_event.step <= after:
        # A pre-mutation snapshot cannot prove that a newly created sheet is
        # missing or that a just-replaced object still has its old definition.
        return [*issues, _issue("workbook.final_inventory_unverified", "current workbook",
                       "native object inventory after final mutation and save",
                       {"last_inspection_step": getattr(inspect_event, "step", None), "after_step": after},
                       actions=actions)]
    sheets = snapshot.get("sheets")
    if not isinstance(sheets, list) or snapshot.get("sheets_omitted_from_context") or snapshot.get("context_truncated"):
        return issues or [_issue("workbook.inventory_incomplete", "current workbook", "complete native inventory",
                                 None, actions=actions)]
    named_sheets = requested_sheet_names(instruction)
    target_sheet = named_sheets[0] if len(named_sheets) == 1 else None
    selected = [s for s in sheets if not target_sheet or s.get("name") == target_sheet]
    if not selected:
        issues.append(_issue("workbook.destination_missing", target_sheet, "instruction-named sheet", None,
                             actions=actions, step=inspect_event.step, mismatch=True))
        return issues
    for key, count in counts.items():
        objects = [(s.get("name"), p) for s in selected for p in s.get(key, []) if isinstance(p, dict)]
        if any(not isinstance(s.get(key), list) or s.get(f"{key}_inspect_error")
               or s.get(f"{key}_omitted_from_context")
               or (key == "pivot_tables" and s.get("pivot_table_count", len(s.get(key, []))) != len(s.get(key, [])))
               for s in selected):
            issues.append(_issue(f"{key}.inventory_incomplete", target_sheet or "current workbook",
                                 "complete native object inventory", None, actions=actions, step=inspect_event.step))
            continue
        # Count distinct live objects; replacements and successful retries do
        # not contribute additional outcomes. Existing objects outside a named
        # new sheet cannot satisfy an instruction to create more objects.
        created = {(ar.get("destination_sheet", ar.get("sheet")), ar.get("name"))
                   for _, a, ar, _ in events if a == ("pivot.create" if key == "pivot_tables" else "chart.create")}
        baseline = {(s.get("name"), p.get("name")) for e, snap in inspections
                    if e.step < mutations[0][0].step for s in snap.get("sheets", [])
                    for p in s.get(key, [])}
        new_objects = [(s, p) for s, p in objects if (s, p.get("name")) not in baseline or (s, p.get("name")) in created]
        if len(new_objects) != count:
            code = "missing_objects" if len(new_objects) < count else "extra_objects"
            issues.append(_issue(f"{key}.{code}", target_sheet or "current workbook", count,
                                 {"count": len(new_objects), "names": [p.get("name") for _, p in new_objects]},
                                 actions=actions, step=inspect_event.step, mismatch=True))
        if key != "pivot_tables":
            continue
        from .calc_percentage_outcomes import request as percentage_request, outcome_issues as percentage_issues

        if percentage_spec := percentage_request(instruction, count):
            issues.extend(percentage_issues(state, events, percentage_spec, new_objects, after, inspect_event.step))
            continue
        spec = _independent_sums(instruction, count)
        if spec is None:
            continue
        source = _source(events, spec)
        if source is None:
            observed_sources = [{"sheet": p.get("source_sheet"), "range": p.get("source_range")}
                                for _, p in objects if p.get("source_sheet") and p.get("source_range")]
            issues.append(_issue("pivot.source_unverified", {**spec, "observed_sources": observed_sources},
                                 "read the complete observed source extent including headers and every data row",
                                 None, actions=actions))
            continue
        valid = {g: [(s, p) for s, p in new_objects if _valid_definition(p, g, source)] for g in source["groups"]}
        bad = [(s, p) for s, p in new_objects if not any(_valid_definition(p, g, source) for g in valid)]
        for sheet, pivot in bad:
            unknown = any(pivot.get(k) is None for k in _definition(pivot)) or pivot.get("inspect_error")
            issues.append(_issue("pivot.definition_unverified" if unknown else "pivot.definition_mismatch",
                                 {"sheet": sheet, "name": pivot.get("name"), "range": pivot.get("output_range")},
                                 {"independent_groupings": source["groups"], "measure": source["measure"],
                                  "aggregation": "sum", "column_fields": [], "page_fields": [],
                                  "source_sheet": source["sheet"], "source_range": source["range"]},
                                 _definition(pivot), actions=actions, step=inspect_event.step, mismatch=not unknown))
        for group, matches in valid.items():
            if len(matches) != 1:
                issues.append(_issue("pivot.grouping_missing_or_duplicate", {"sheet": target_sheet, "group": group},
                                     "exactly one independent sum pivot", [p.get("name") for _, p in matches],
                                     actions=actions, step=inspect_event.step, mismatch=True))
            else:
                sheet, pivot = matches[0]
                issue = _output_issue(events, sheet, pivot, source["totals"][group], after)
                if issue:
                    issues.append(issue)
        for i, (sheet, pivot) in enumerate(new_objects):
            for other_sheet, other in new_objects[i + 1:]:
                if sheet == other_sheet and _overlap(rectangle(pivot.get("output_range")), rectangle(other.get("output_range"))):
                    issues.append(_issue("pivot.outputs_overlap", sheet, "disjoint pivot output ranges",
                                         [pivot.get("name"), other.get("name")], actions=actions,
                                         step=inspect_event.step, mismatch=True))
    return issues


def outcome_retry_allowed(state: Any, domain: str, action: str, args: dict, after_step: int) -> bool:
    """Allow one model-selected reapplication after fresh native contradiction."""
    if domain == "os" and action == "filesystem.set_permissions":
        return any(issue["code"] == "permissions.mode_mismatch"
                   and issue["target"].get("path") == args.get("path")
                   and issue["evidence_step"] > after_step
                   and str(args.get("mode", "")).lstrip("0") == issue["expected"]["mode"].lstrip("0")
                   for issue in completion_outcome_issues(state))
    if domain != "libreoffice_calc" or action != "pivot.create":
        return False
    for issue in completion_outcome_issues(state):
        target = issue["target"]
        if (issue["kind"] != "state_mismatch" or not isinstance(target, dict)
                or issue.get("evidence_step", 0) <= after_step
                or target.get("name") != args.get("name")
                or target.get("sheet") != args.get("destination_sheet")
                or not args.get("replace")):
            continue
        if issue["code"] == "pivot.output_mismatch":
            return True
        if issue["code"] == "pivot.definition_mismatch":
            expected = issue["expected"]
            if expected.get("aggregation") == "count":
                from .calc_percentage_outcomes import valid_definition

                source = {"sheet": expected["source_sheet"], "range": expected["source_range"]}
                candidate = {"column_fields": [], "page_fields": [], **args}
                if any(valid_definition(candidate, group, source) for group in expected["independent_groupings"]):
                    return True
                continue
            source = {"sheet": expected["source_sheet"], "range": expected["source_range"],
                      "measure": expected["measure"]}
            candidate = {"column_fields": [], "page_fields": [], **args}
            candidate["data_fields"] = [
                {"aggregation": "sum", **f} for f in args.get("data_fields", [])
            ]
            if any(_valid_definition(candidate, group, source) for group in expected["independent_groupings"]):
                return True
    return False
