"""Read-only progress for the latest observed Writer format query.

Queries are observations, never an automatically adopted task scope. Only
native formats and exact body ranges are compared; no tool call is generated.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


_FIELDS = {"font_size", "bold", "italic", "script"}
_READS = {"text.find", "document.inspect", "document.save", "document.export_pdf"}
_FORMATS = {"text.set_format", "text.set_format_in_match"}
_REJECTS = {"INVALID_REQUEST", "TEXT_MISMATCH", "TEXT_NOT_FOUND", "TEXT_MATCH_NOT_FOUND"}
_CONTROLS = {"tools_search", "completion_revise", "propose_done", "fail_task"}


def _range(value: dict[str, Any]) -> tuple[int, int, int] | None:
    if not isinstance(value, dict):
        return None
    fields = tuple(value.get(key) for key in ("paragraph_index", "start_offset", "end_offset"))
    if any(type(item) is not int for item in fields):
        return None
    paragraph, start, end = fields
    return fields if paragraph >= 0 and 0 <= start < end else None


def _route(event, domain):
    proposed = getattr(event, "proposed", {}) or {}
    args = proposed.get("arguments", {})
    args = args if isinstance(args, dict) else {}
    result = getattr(event, "result", None)
    hint = result.get("context_hint") if isinstance(result, dict) else None
    owner = domain
    action = proposed.get("action", "")
    if isinstance(hint, dict) and "downstream_adapter" in hint:
        owner = hint.get("downstream_adapter")
        action = hint.get("downstream_action")
        hint = hint.get("downstream_context")
        payload = args.get("payload")
        args = payload.get("params", {}) if isinstance(payload, dict) else {}
    elif domain == "multi_apps" and isinstance(args, dict):
        owner = args.get("adapter")
        action = args.get("action")
        payload = args.get("payload")
        args = payload.get("params", {}) if isinstance(payload, dict) else {}
    args = args if isinstance(args, dict) else {}
    return proposed, owner, action, args, hint


def writer_format_progress(events: list[Any], domain: str) -> dict[str, Any] | None:
    """Reconstruct bounded evidence without changing stored events or arguments."""
    if domain not in {"libreoffice_writer", "multi_apps"}:
        return None
    query = None
    invalid = None

    def invalidate(event, reason):
        nonlocal query, invalid
        if query is not None:
            invalid = {"query_step": query["step"], "status": "invalidated",
                       "invalidated_at_step": getattr(event, "step", None), "reason": reason,
                       "guidance": "Prior ranges/formats are unknown; read current Writer ranges before relying on this progress."}
        query = None

    for event in events:
        proposed, owner, action, args, hint = _route(event, domain)
        if proposed.get("tool") in _CONTROLS:
            continue
        if proposed.get("kind") == "gui" or proposed.get("tool") == "gui_action":
            invalidate(event, "GUI effects on the document are not established by native readback")
            continue
        if owner != "libreoffice_writer":
            invalidate(event, "operation outside the observed Writer document")
            continue
        if not getattr(event, "executed", False):
            error = getattr(event, "error", None) or {}
            code = (error.get("error") or {}).get("code")
            if code not in _REJECTS:
                invalidate(event, "failed operation may have partial effects")
            continue
        if not isinstance(hint, dict):
            invalidate(event, "operation lacks native observation")
            continue
        identity = hint.get("identity") or {}
        identity = identity if isinstance(identity, dict) else {}
        url = identity.get("url")
        if query is not None and url and url != query["identity"]["url"]:
            invalidate(event, "observed document changed")

        if action == "text.find" and isinstance(hint.get("format"), dict) and hint["format"]:
            matches = hint.get("matches")
            if not url or not isinstance(matches, list) or len(matches) > 256:
                invalidate(event, "format query lacks stable document identity or complete range records")
                continue
            observed = {}
            for match in matches:
                key = _range(match)
                if (key is None or key in observed or not isinstance(match.get("format"), dict)
                        or not isinstance(match.get("matched_text"), str)):
                    break
                observed[key] = {"match": deepcopy(match), "format": deepcopy(match["format"])}
            else:
                query = {"step": getattr(event, "step", None), "identity": deepcopy(identity),
                         "filter": deepcopy(hint["format"]), "literal": hint.get("literal"),
                         "has_more": hint.get("has_more") is not False,
                         "reported_count": hint.get("returned_count"), "matches": observed,
                         "comparison": None}
                invalid = None
                continue
            invalidate(event, "format query has ambiguous range records")
            continue
        if query is None:
            continue
        if not url:
            invalidate(event, "operation lacks stable document identity")
            continue
        if action in _READS:
            continue
        if action not in _FORMATS or not url or hint.get("text_unchanged") is not True:
            invalidate(event, "text or untracked formatting may have changed")
            continue
        key = _range(hint)
        observed_format = hint.get("format")
        if key is None or not isinstance(observed_format, dict):
            invalidate(event, "format action lacks exact native range and format readback")
            continue
        requested = {name: args[name] for name in _FIELDS if name in args}
        relevant = False
        for target, value in query["matches"].items():
            paragraph, start, end = target
            if paragraph != key[0] or end <= key[1] or start >= key[2]:
                continue
            relevant = True
            if target == key and value["match"].get("matched_text") == hint.get("text"):
                value["format"] = deepcopy(observed_format)
            else:
                # A partial or wider mutation does not prove a full match's format.
                value["format"] = None
        if relevant and requested:
            query["comparison"] = requested

    if query is None:
        return invalid
    comparison = query["comparison"]
    unconfirmed = []
    confirmed = 0
    for key, value in query["matches"].items():
        fmt = value["format"]
        if comparison and isinstance(fmt, dict) and all(fmt.get(k) == v for k, v in comparison.items()):
            confirmed += 1
            continue
        match = value["match"]
        text = match.get("matched_text", "")
        row = {"paragraph_index": key[0], "start_offset": key[1], "end_offset": key[2],
               "matched_text": text[:120], "last_known_format": fmt}
        if len(text) > 120:
            row.update(text_truncated=True, text_length=len(text))
        unconfirmed.append(row)
    return {
        "status": "observed_query_only", "identity": query["identity"], "query_step": query["step"],
        "query_format": query["filter"], "query_literal": query["literal"],
        "scope": "returned_matches_only", "has_more": query["has_more"],
        "observed_match_count": len(query["matches"]),
        "native_returned_count": query["reported_count"],
        "comparison_format": comparison,
        "matching_readback_count": confirmed if comparison else None,
        "unconfirmed_count": len(unconfirmed) if comparison else None,
        "unconfirmed_ranges": unconfirmed[:8],
        "ranges_omitted_count": max(0, len(unconfirmed) - 8),
        "guidance": (
            "Readback progress for this observed query, not task completion or a requirement "
            "to edit every match. comparison_format comes from the model's latest relevant "
            "format call. Unconfirmed ranges have no matching full-range readback; compare "
            "the user's requested scope. has_more means the query is partial."
        ),
    }
