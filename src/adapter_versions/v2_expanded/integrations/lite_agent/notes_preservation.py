"""Observe blank-note scope and preserve existing notes; never author note text."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any

from .completion_policy import action_is_read_only, effective_canonical_action
from .presentation_notes_transfer_semantics import requests_missing_notes_transfer
from .result_envelopes import iter_result_mappings
from .adapter_results import _billing_text_batch_files


def source_texts(state: Any) -> dict[str, str]:
    """Reconstruct completely observed source text, without selecting slide content."""
    named = set(re.findall(r"[\w.-]+\.(?:docx?|odt|txt|md|pdf)\b", state.instruction, re.I))
    sources: dict[str, dict] = {}
    readers = {"document.read_file", "document.inspect", "file.read_text",
               "pdf.extract_text_batch", "image.extract_text_batch"}
    for event in state.events:
        if not event.executed or event.error or event.proposed.get("kind") != "adapter":
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        if domain == "libreoffice_impress":
            continue  # Destination observations are not the requested source script.
        path_arg = args.get("path", args.get("input_path"))
        if action not in readers:
            if not action_is_read_only(action) and isinstance(path_arg, str):
                sources.pop(path_arg, None)
            continue
        items = _billing_text_batch_files(event.result)
        items += [body for body in iter_result_mappings(event.result)
                  if isinstance(body.get("text"), str)]
        for item in items:
            path = item.get("path", path_arg)
            text = item.get("text")
            if (not isinstance(path, str) or not isinstance(text, str) or not text.strip()
                    or item.get("status", "ok") != "ok"
                    or "...<truncated>..." in text
                    or (named and PurePosixPath(path).name not in named)):
                continue
            start, end, total = (item.get(key) for key in
                                 ("source_start_char", "source_end_char", "source_total_chars"))
            window = all(isinstance(n, int) and not isinstance(n, bool)
                         for n in (start, end, total))
            if window:
                if not (0 <= start <= end <= total and len(text) == end - start):
                    continue
                source = sources.setdefault(path, {"total": total, "windows": []})
                if source["total"] != total or (start == 0 and end == total):
                    source = sources[path] = {"total": total, "windows": []}
                source["windows"].append((start, end, text))
            elif (item.get("source_truncated") is False
                  and not item.get("has_more") and not item.get("next_start_char")
                  and not item.get("context_truncated")):
                sources[path] = {"total": len(text), "windows": [(0, len(text), text)]}
    complete = {}
    for path, source in sources.items():
        observed = ""
        for start, end, text in sorted(source["windows"]):
            if start > len(observed):
                break
            overlap = min(len(observed), end) - start
            if overlap > 0 and observed[start:start + overlap] != text[:overlap]:
                observed = ""
                break  # Conflicting observations cannot establish a source.
            observed += text[max(0, overlap):]
        if len(observed) == source["total"] > 0:
            complete[path] = observed
    return complete


def source_read_evidence(state: Any) -> list[str]:
    return list(source_texts(state))


# Only validate a model-selected, explicitly numbered heading. Never choose a
# heading, target or excerpt on the model's behalf; unknown labels fail closed.
_PAGE_HEADING = re.compile(r"(?im)^[ \t]*((?:slide|page)[ \t]+(\d+)[ \t]*[:：]?[ \t]*)$")


def reference_errors(state: Any, index: int, text: str, reference: Any) -> list[str]:
    if not isinstance(reference, dict):
        return ["Provide source_reference.path and source_reference.heading from the read "
                "script for this page. text selects the entire original passage below that "
                "heading; preserve its internal newlines, spaces and punctuation. "
                f"Human page {index + 1} = API index {index}. No mutation executed."]
    path = reference.get("path")
    source = source_texts(state).get(path) if isinstance(path, str) else None
    heading = reference.get("heading")
    if source is None or not isinstance(heading, str):
        return ["source_reference must identify a completely read source path and its "
                "observed page heading. Read the source again if it has changed. No mutation executed."]
    headings = list(_PAGE_HEADING.finditer(source))
    matches = [(i, h) for i, h in enumerate(headings) if h.group(1).strip() == heading]
    if len(matches) != 1:
        return ["The selected source heading is absent, ambiguous or not an explicitly "
                "numbered Slide/Page heading. Select the exact observed heading. No mutation executed."]
    position, selected = matches[0]
    page = int(selected.group(2))
    if page != index + 1:
        return [f"Source heading {heading!r} identifies human page {page}, but target "
                f"API index {index} identifies human page {index + 1}. Select the matching "
                "source heading and original passage. No mutation executed."]
    end = headings[position + 1].start() if position + 1 < len(headings) else len(source)
    passage = source[selected.end():end].strip()
    if text != passage:
        return [f"Human page {index + 1} (API index {index}): text differs from the entire "
                f"observed passage under {heading!r}. Copy that passage verbatim; only "
                "surrounding heading indentation/blank space is excluded. Do not collapse "
                "internal newlines or spaces, omit sentences, or use another page's text. "
                "No mutation executed."]
    return []


def source_read_errors(state: Any) -> list[str]:
    if source_read_evidence(state):
        return []
    return ["The instruction asks to transfer an existing script from its source file. "
            "No complete source-text read is recorded. Locate the source at the location "
            "specified in the instruction using public tools_search/file tools and read "
            "its text, including any continuation. Do not invent remarks or ask for text "
            "by typing into the desktop application. Keep the original text; the model "
            "chooses the source and target page. No mutation executed."]


def _may_change_existing_notes(instruction: str) -> bool:
    """Keep unrelated body edits separate; ambiguous edit objects opt out."""
    verbs = r"replace|rewrite|overwrite|revise|correct|delete|remove"
    actions = rf"{verbs}|hide|apply|keep|preserve|add|fill|complete|insert|copy|transfer"
    modifiers = r"(?:(?:merely|just|simply|only|ever|please)\s+)*"
    command_prefix = rf"(?:(?:do\s+not|don't|never|do|please\s+do)\s+)?{modifiers}"
    # Sentences and explicit transitions start independent commands. Within a
    # coordinated command, negation also covers later verbs and modifiers:
    # 'Do not merely hide it, remove a bullet, or apply formatting'. Split
    # only before another verb so 'replace titles and notes' keeps its objects.
    clauses = re.split(
        r"[;.!?\n]+|\b(?:then|also|but|however|instead|while)\b",
        instruction, flags=re.I,
    )
    for clause in clauses:
        negative = False
        fragments = re.split(
            rf"(?:,\s*(?:(?:and|or)\s+)?|\b(?:and|or)\s+)"
            rf"(?={command_prefix}(?:{actions})\b)", clause, flags=re.I,
        )
        for fragment in fragments:
            for match in re.finditer(rf"\b(?:{actions})\b", fragment, re.I):
                prefix = fragment[:match.start()]
                if re.search(rf"\b(?:do\s+not|don't|never)\s+{modifiers}$", prefix, re.I):
                    negative = True
                elif re.search(rf"\bdo\s+{modifiers}$", prefix, re.I):
                    negative = False  # Explicit affirmative 'and do remove ...'.
                if negative or not re.fullmatch(verbs, match.group(), re.I):
                    continue
                target = fragment[match.end():]
                if _notes_edit_object(target):
                    return True
    return False


def _notes_edit_object(target: str) -> bool:
    """A positive edit of notes or an ambiguous object may change notes."""
    # Pronouns and unspecified objects remain outside this protection rather
    # than blocking a possibly requested edit of existing notes.
    direct_object = re.split(r"\b(?:from|with|using|in|on|of|to)\b", target,
                             maxsplit=1, flags=re.I)[0]
    if re.search(r"\b(?:notes?|remarks?)\b", direct_object, re.I):
        return True
    if re.search(r"\b(?:paragraphs?|text|words?)\b", direct_object, re.I) and re.search(
        r"\b(?:from|in|of)\s+(?:(?:the|existing|speaker|speaking|presenter|slide)\s+)*"
        r"(?:notes?|remarks?)\b", target, re.I,
    ):
        return True
    return not re.search(r"\b(?:paragraphs?|text\s+box(?:es)?|body|titles?|"
                         r"subtitles?|shapes?|pictures?|images?|slides?|"
                         r"backgrounds?|tables?)\b", direct_object, re.I)


def requested(state: Any) -> bool:
    text = state.instruction
    return (
        state.domain in {"multi_apps", "libreoffice_impress"}
        and requests_missing_notes_transfer(text)
        and not _may_change_existing_notes(text)
    )


def _payload(event: Any) -> dict:
    candidates = list(iter_result_mappings(event.result))
    # Prefer full native evidence over summaries or previews.
    for item in reversed(candidates):
        if isinstance(item.get("slides"), list) and "slide_count" in item:
            if not item.get("context_truncated") and not item.get("truncated"):
                return item
    hint = (event.result or {}).get("context_hint", {})
    if isinstance(hint, dict):
        hint = hint.get("downstream_context", hint)
        if isinstance(hint, dict) and isinstance(hint.get("slides"), list):
            return hint
    return {}


def _snapshot(state: Any) -> dict:
    documents: dict[str, dict] = {}
    current = None
    for event in state.events:
        kind = event.proposed.get("kind")
        if kind == "gui" and (event.executed or event.validated):
            for doc in documents.values():
                doc["live"].clear()
                doc["last_change"] = event.step
            continue
        if kind != "adapter":
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        if domain != "libreoffice_impress":
            continue
        success = event.executed and not event.error
        if action in {"presentation.open", "presentation.create_new", "presentation.close"} and success:
            current = None
            continue
        if action == "presentation.inspect" and success:
            payload = _payload(event)
            url = (payload.get("identity") or {}).get("url") or payload.get("url")
            if not isinstance(url, str) or not url:
                continue
            current = documents.setdefault(url, {
                "initial": {}, "live": {}, "writes": {}, "changed_pages": set(), "count": None,
                "last_change": 0, "last_save": 0, "uncertain_structure": False,
            })
            count = payload.get("slide_count")
            if isinstance(count, int) and not isinstance(count, bool):
                if current["count"] is not None and current["count"] != count:
                    current["uncertain_structure"] = True
                current["count"] = count
            for slide in payload.get("slides", []):
                index = slide.get("slide", slide.get("slide_index"))
                text = slide.get("notes")
                if (isinstance(index, int) and not isinstance(index, bool)
                        and isinstance(text, str) and not slide.get("notes_truncated")
                        and "...<truncated>..." not in text):
                    if index not in current["changed_pages"]:
                        current["initial"].setdefault(index, text)
                    current["live"][index] = (text, event.step)
            continue
        if current is None:
            continue
        if action in {"presentation.save", "presentation.save_as"} and success:
            current["last_save"] = event.step
        elif not action_is_read_only(action) and (event.executed or event.validated):
            current["last_change"] = event.step
            if action == "slide.set_notes":
                index = args.get("slide")
                current["changed_pages"].add(index)
                current["live"].pop(index, None)
                if success:
                    current["writes"][index] = args
            else:
                current["live"].clear()
                if action in {"slide.create", "slide.delete", "slide.move", "slide.duplicate"}:
                    current["uncertain_structure"] = True
    return current or {}


def argument_errors(state: Any, action: str, args: dict) -> list[str]:
    if not requested(state):
        return []
    candidate = SimpleNamespace(proposed={"action": action, "arguments": args})
    domain, action, args = effective_canonical_action(candidate, state.domain)
    if domain != "libreoffice_impress" or action != "slide.set_notes":
        return []
    snapshot = _snapshot(state)
    index = args.get("slide")
    original = snapshot.get("initial", {}).get(index)
    live = snapshot.get("live", {}).get(index)
    if snapshot.get("uncertain_structure") or original is None or live is None:
        return [f"Inspect the live notes of slide index {index} before writing. "
                "Only missing notes may be filled; unknown or stale notes are not blank. "
                "No mutation executed."]
    if original.strip() and args.get("text") != original:
        return [f"Display slide {index + 1} already had notes. The instruction only asks "
                "to complete missing notes: preserve its original text, spaces and punctuation. "
                "Skip this page. If restoring a changed page, read the observed original "
                "text with presentation.inspect and restore it exactly. No mutation executed."]
    # Exact restoration of a previously completed page does not need a script.
    if original.strip():
        return []
    return source_read_errors(state) or reference_errors(
        state, index, args.get("text"), args.get("source_reference"))


def model_progress(state: Any) -> dict | None:
    """Separate observable status from document text and sensitive error prose."""
    if not requested(state):
        return None
    snapshot = _snapshot(state)
    if not snapshot:
        return None
    pages = []
    final_step = max(snapshot["last_change"], snapshot["last_save"])
    save_required = bool(snapshot["last_change"] and snapshot["last_save"] <= snapshot["last_change"])
    for index, original in sorted(snapshot["initial"].items()):
        live = snapshot["live"].get(index)
        if original.strip():
            status = ("original retained; no write needed" if live and live[0] == original
                      else "original content requires inspection or exact restoration")
        elif live and live[0].strip():
            reference = snapshot["writes"].get(index, {}).get("source_reference")
            status = ("filled and source checked" if not reference_errors(state, index, live[0], reference)
                      else "filled text requires source correction")
        elif index in snapshot["writes"] and live is None:
            status = "written; current text requires read-back"
        else:
            status = "blank or unverified; fill only from the observed source"
        pages.append({"display_slide_number": index + 1, "slide_index": index,
                      "initially_had_notes": bool(original.strip()), "status": status,
                      "final_readback_required": save_required or live is None or live[1] <= final_step})
    return {
        "slide_count": snapshot["count"], "pages": pages[:64],
        "pages_omitted": max(0, len(pages) - 64),
        "initial_inventory_complete": (not snapshot["uncertain_structure"]
                                       and snapshot["count"] is not None
                                       and set(snapshot["initial"]) == set(range(snapshot["count"]))),
        "save_required": save_required,
        "guidance": (
            "Pages marked original retained already satisfy the preservation requirement; "
            "do not rewrite them to match source formatting. Original text is available via "
            "presentation.inspect. A rejected change did not create unfinished work on an "
            "already completed page. All filled pages still require document save and "
            "post-save read-back. If a needed operation is undiscovered, use tools_search."
        ),
    }


def outcome_issues(state: Any, issue: Any) -> list[dict]:
    if not requested(state):
        return []
    snapshot = _snapshot(state)
    actions = (("adapter.call", "tools_search") if state.domain == "multi_apps" else
               ("presentation.inspect", "slide.set_notes", "presentation.save"))

    def defect(code, target, expected, observed, mismatch=False):
        return issue("notes." + code, target, expected, observed,
                     actions=actions, mismatch=mismatch)

    source_issues = ([defect("source_unread", "source script",
                            source_read_errors(state)[0], None)]
                     if snapshot and source_read_errors(state) else [])
    if not any(e.executed and effective_canonical_action(e, state.domain)[:2]
               == ("libreoffice_impress", "slide.set_notes") for e in state.events):
        return source_issues
    count = snapshot.get("count")
    if (not isinstance(count, int) or snapshot.get("uncertain_structure")
            or set(snapshot.get("initial", {})) != set(range(count))):
        return [defect("initial_scope_unverified", "presentation notes",
                       "observe every page's initial notes before changing that page",
                       sorted(snapshot.get("initial", {})))]
    issues = source_issues
    for index, original in snapshot["initial"].items():
        live = snapshot["live"].get(index)
        target = f"display slide {index + 1} (API index {index})"
        if live is None:
            issues.append(defect("unverified", target, "inspect current notes", None))
            continue
        text, step = live
        if original.strip() and text != original:
            issues.append(defect("existing_changed", target, original, text, True))
        elif not original.strip() and not text.strip():
            issues.append(defect("missing", target, "fill this blank page from the source notes", text, True))
        elif not original.strip():
            write = snapshot["writes"].get(index, {})
            errors = reference_errors(state, index, text, write.get("source_reference"))
            if errors:
                issues.append(defect("source_mismatch", target, errors[0], text, True))
        if step <= max(snapshot["last_change"], snapshot["last_save"]):
            issues.append(defect("final_readback_required", target,
                                 "read notes after the final change and save", step))
    if snapshot["last_change"] and snapshot["last_save"] <= snapshot["last_change"]:
        issues.append(defect("save_required", "presentation",
                             "presentation.save after the final change", snapshot["last_save"]))
    return issues
