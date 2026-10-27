"""Observe blank-note scope and preserve existing notes; never author note text."""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from .completion_policy import action_is_read_only, effective_canonical_action
from .presentation_notes_transfer_semantics import requests_missing_notes_transfer
from .result_envelopes import iter_result_mappings


def requested(state: Any) -> bool:
    text = state.instruction
    scope = re.sub(r"\b(?:do not|don't|never)\s+(?:replace|rewrite|overwrite|revise|correct|delete|remove)\b",
                   "", text, flags=re.I)
    return (
        state.domain in {"multi_apps", "libreoffice_impress"}
        and requests_missing_notes_transfer(text)
        # Explicit replacement is a different scope, even when "existing" appears.
        and not re.search(r"\b(?:replace|rewrite|overwrite|revise|correct|delete|remove)\b", scope, re.I)
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
                "initial": {}, "live": {}, "changed_pages": set(), "count": None,
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
                "Skip this page; if restoring a changed page, use the observed original text "
                f"exactly: {original!r}. No mutation executed."]
    return []


def outcome_issues(state: Any, issue: Any) -> list[dict]:
    if not requested(state):
        return []
    # Discovery must remain available until the first actual notes mutation.
    if not any(e.executed and effective_canonical_action(e, state.domain)[:2]
               == ("libreoffice_impress", "slide.set_notes") for e in state.events):
        return []
    snapshot = _snapshot(state)
    actions = (("adapter.call", "tools_search") if state.domain == "multi_apps" else
               ("presentation.inspect", "slide.set_notes", "presentation.save"))

    def defect(code, target, expected, observed, mismatch=False):
        return issue("notes." + code, target, expected, observed,
                     actions=actions, mismatch=mismatch)

    count = snapshot.get("count")
    if (not isinstance(count, int) or snapshot.get("uncertain_structure")
            or set(snapshot.get("initial", {})) != set(range(count))):
        return [defect("initial_scope_unverified", "presentation notes",
                       "observe every page's initial notes before changing that page",
                       sorted(snapshot.get("initial", {})))]
    issues = []
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
        if step <= max(snapshot["last_change"], snapshot["last_save"]):
            issues.append(defect("final_readback_required", target,
                                 "read notes after the final change and save", step))
    if snapshot["last_change"] and snapshot["last_save"] <= snapshot["last_change"]:
        issues.append(defect("save_required", "presentation",
                             "presentation.save after the final change", snapshot["last_save"]))
    return issues
