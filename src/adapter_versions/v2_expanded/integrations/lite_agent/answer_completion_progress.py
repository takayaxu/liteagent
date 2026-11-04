"""Concrete evidence-based hints for completing an existing numbered answer sheet.

This module never solves a question, writes an answer, restricts tools or accepts
completion. All suggested mutations leave replacement content to the model.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

from .completion_policy import action_is_read_only, effective_canonical_action
from .notes_preservation import source_texts


_SECTION = re.compile(r"(?im)^([^\n]*\b(?:test|exam|quiz)\s+(\d+)\s*:)[ \t]*$")
_NUMBER = re.compile(r"(?i)\b(?:test|exam|quiz)[ _-]*(\d+)\b")


def _requested(state: Any) -> bool:
    text = state.instruction.lower()
    return (state.domain == "multi_apps" and "answer" in text and "format" in text
            and bool(re.search(r"\b(?:doc|document|file)\b", text))
            and bool(re.search(r"\b(?:remaining|rest|complete|fill)\b", text)))


def _context(event: Any) -> dict:
    result = event.result if isinstance(event.result, dict) else {}
    hint = result.get("context_hint", {})
    return hint.get("downstream_context", hint) if isinstance(hint, dict) else {}


def _sections(text: str) -> list[dict]:
    headings = list(_SECTION.finditer(text))
    return [{"heading": match[1], "number": match[2],
             "entry": text[match.end():headings[i + 1].start()
                           if i + 1 < len(headings) else len(text)].strip()}
            for i, match in enumerate(headings)]


def _call(tools: list[dict], adapter: str, action: str, params: dict) -> dict:
    routes = {(r.get("adapter"), r.get("action")) for tool in tools
              for r in tool.get("function", {}).get("parameters", {}).get("x-allowed-routes", [])
              if isinstance(r, dict)}
    names = {tool.get("function", {}).get("name") for tool in tools}
    if (adapter, action) in routes:
        if action == "text.find_replace" and not params:
            return {}  # The model must derive replacement content from questions.
        return {"name": "adapter__adapter_call", "arguments": {
            "adapter": adapter, "action": action, "payload": {"params": params}}}
    if "tools_search" in names:
        # Source-handoff filters may hide an additional reader until a mutation
        # is discovered too. Search both needed public capabilities explicitly.
        query = adapter + " " + action
        if action == "document.read_file":
            query += " text.find_replace"
        return {"name": "tools_search", "arguments": {"query": query}}
    return {}


def model_progress(state: Any, tools: list[dict] | None = None) -> dict | None:
    if not _requested(state):
        return None
    tools = tools or []
    complete = source_texts(state)
    discovered: list[str] = []
    reads: dict = {}
    first_target = None
    current_target = None
    active_path = None
    latest_mutation = latest_save = 0
    for event in state.events:
        if not event.executed or event.error:
            continue
        if event.proposed.get("kind") == "gui":
            if event.proposed.get("arguments", {}).get("action") in {"type", "press", "hotkey"}:
                latest_mutation = event.step
            continue
        if event.proposed.get("kind") != "adapter":
            continue
        adapter, action, args = effective_canonical_action(event, state.domain)
        context = _context(event)
        if action == "filesystem.find":
            for item in context.get("matches", []):
                path = item.get("path")
                if (item.get("kind") == "file" and isinstance(path, str)
                        and PurePosixPath(path).suffix.lower() in {".docx", ".doc", ".odt", ".rtf"}
                        and path not in discovered):
                    discovered.append(path)
        if action == "desktop.open_path":
            path = args.get("path")
            if isinstance(path, str) and PurePosixPath(path).suffix.lower() in {".docx", ".doc", ".odt", ".rtf"}:
                active_path = path
        if adapter == "libreoffice_writer" and action == "document.inspect":
            url = context.get("url", context.get("identity", {}).get("url"))
            if isinstance(url, str) and url.startswith("file://"):
                active_path = unquote(url.removeprefix("file://"))
        if action == "document.read_file":
            for item in context.get("files", []):
                path, text = item.get("path"), item.get("text")
                if not isinstance(path, str) or not isinstance(text, str):
                    continue
                reads[path] = {**item, "step": event.step}
                sections = _sections(text)
                if (item.get("source_start_char") == 0 and len(sections) >= 2
                        and any(s["entry"] and re.fullmatch(r"[a-zA-Z\s,;.()-]+", s["entry"])
                                for s in sections)):
                    target = {"path": path, "text": text, "sections": sections, "read_step": event.step}
                    if first_target is None:
                        first_target = target
                    if first_target["path"] == path:
                        current_target = target
        if adapter == "libreoffice_writer" and not action_is_read_only(action):
            if action == "document.save":
                latest_save = event.step
            elif not action.startswith("document.export"):
                latest_mutation = event.step
    target = current_target or first_target
    original = first_target
    known_path = target["path"] if target else next((path for path in discovered
                 if re.search(r"(?i)\b(?:answer|answers|solution|solutions|key)\b", PurePosixPath(path).stem)), None)
    progress: dict = {"target": target, "original_target": original,
                      "active_path": active_path, "discovered_documents": discovered,
                      "latest_mutation_step": latest_mutation, "latest_save_step": latest_save,
                      "meaning": "Observed state and next-call guidance, not independent answer correctness or acceptance. "
                                 "Solve the questions yourself; preserve existing answers and formatting."}

    def step(stage: str, instruction: str, adapter: str | None = None,
             action: str | None = None, params: dict | None = None) -> dict:
        progress.update(stage=stage, next_step=instruction)
        if adapter and action:
            call = _call(tools, adapter, action, params or {})
            if call:
                progress["suggested_tool_call"] = call
                if call["name"] == "tools_search":
                    progress["next_step"] = ("Call tools_search now with the exact suggested query. "
                        "The required operation is absent from this turn's routes. " + instruction)
        return progress

    if known_path is None:
        return step("locate_documents", "Find the existing answer document and source tests. Use actual "
                    "returned paths; do not guess folder spelling or filenames, or open by mouse coordinates. "
                    "filesystem.find roots must be absolute or ~ paths. If a named folder is empty, "
                    "inspect its parent or other observed locations, rather than repeating the empty search.",
                    "os", "filesystem.find", {"roots": ["~"], "name_patterns": ["*.docx", "*.doc", "*.odt", "*.rtf"],
                                              "kind": "file", "recursive": True, "max_results": 60})
    if target is None:
        return step("read_existing_answers", "Read the observed answer document first to learn its existing "
                    "answers, blank section headings and exact output format. A successful read_file reads "
                    "saved content; it does not activate that file for editing.", "libreoffice_writer",
                    "document.read_file", {"path": known_path, "max_chars": 12000})
    if latest_mutation > latest_save:
        if active_path != known_path:
            return step("activate_target", "Open the observed target document before saving or editing; "
                        "read_file does not change the active Writer document.", "os", "desktop.open_path", {"path": known_path})
        return step("save_current_edits", "Save the active answer document now. Saved-file reads cannot "
                    "verify unsaved GUI typing or live Writer edits. Do not keep rereading the old disk snapshot.",
                    "libreoffice_writer", "document.save")
    if latest_save > target["read_step"]:
        return step("read_saved_answers", "Read the saved target now and compare with the original. "
                    "Check existing answers remain exact and every requested blank section has one answer "
                    "sequence in the example's format.", "libreoffice_writer", "document.read_file",
                    {"path": known_path, "max_chars": 12000})
    blanks = [s for s in target["sections"] if not s["entry"]]
    progress["blank_sections"] = blanks
    changed = [s for s in original["sections"] if s["entry"] and not any(
        t["heading"] == s["heading"] and t["entry"] == s["entry"] for t in target["sections"])]
    progress["existing_answer_changes"] = changed
    if changed:
        return step("restore_existing_answers", "Restore the changed original answer entries exactly "
                    "from original_target using a unique observed text anchor. The task asks to complete "
                    "blank sections, not rewrite provided answers. Use text.find_replace, then save and read back.",
                    "libreoffice_writer", "text.find_replace")
    source_evidence = []
    for blank in [s for s in original["sections"] if not s["entry"]]:
        candidates = [p for p in discovered if p != known_path and (
            (match := _NUMBER.search(PurePosixPath(p).stem)) and match[1] == blank["number"])]
        observed = [(p, text) for p, text in complete.items() if p != known_path and (
            (match := _NUMBER.search(text.splitlines()[0] if text.splitlines() else ""))
            and match[1] == blank["number"])]
        if not observed:
            if not any(s["heading"] == blank["heading"] for s in blanks):
                continue
            if not candidates:
                return step("locate_missing_source", "Find the source for the observed blank section "
                            + blank["heading"] + ". Search actual document paths, including the parent "
                            "of an empty folder. Do not infer answers from a heading alone.",
                            "os", "filesystem.find", {"roots": ["~"], "name_patterns": ["*.docx", "*.doc", "*.odt", "*.rtf"],
                                                      "kind": "file", "recursive": True, "max_results": 60})
            path = candidates[0]
            previous = reads.get(path, {})
            start = previous.get("source_start_char", 0) + len(previous.get("text", "")) if previous else 0
            return step("read_source_questions", "Read the actual source for " + blank["heading"]
                        + ". Follow any missing character continuation; do not reread a completed source "
                        "or edit the test document. Search includes text.find_replace to retain the future "
                        "editing capability while discovering this additional reader.", "libreoffice_writer",
                        "document.read_file", {"path": path, "start_char": start, "max_chars": 12000})
        source_evidence.extend({"path": p, "text": text[:9000], "text_omitted": len(text) > 9000}
                               for p, text in observed)
    progress["source_questions"] = source_evidence
    if not blanks:
        return step("verify_completion", "Every observed answer section has content in the saved target. "
                    "Now check each newly added option against its source question, sequence length and "
                    "the example format; content presence is not correctness. Preserve provided answers. "
                    "If all requested entries are correct, claim completion with the saved target path.")
    if active_path != known_path:
        return step("activate_target", "Open this exact answer document for editing. Source reads do not "
                    "activate it. Do not type into a test or at guessed screen coordinates.",
                    "os", "desktop.open_path", {"path": known_path})
    progress["write_contract"] = {"adapter": "libreoffice_writer", "action": "text.find_replace",
        "observed_empty_heading_anchors": [s["heading"] for s in blanks],
        "replace_all": False, "case_sensitive": True,
        "replacement_rule": "Keep the chosen heading unchanged, append an actual paragraph boundary "
                            "(JSON \r), then your solved option sequence in the existing example format."}
    return step("solve_and_fill_one_section", "Solve the multiple-choice questions in source_questions "
                "for one blank section. Follow the existing answer sequence format; do not answer unrelated "
                "essay/fill-in sections or add explanations absent from the example. Use text.find_replace: "
                "find an exact empty heading from write_contract, replacement preserves that heading and "
                "adds a paragraph plus your computed answers; replace_all=false, case_sensitive=true. "
                "Do not use GUI typing, append at an unknown cursor, or treat DOCX as a UTF-8 text file. "
                "After successful replacement, save, read back and continue with the remaining blank section.",
                "libreoffice_writer", "text.find_replace")
