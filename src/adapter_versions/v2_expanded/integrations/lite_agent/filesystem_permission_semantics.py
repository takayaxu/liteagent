"""Generic intent detection for regular-file permission changes."""

from __future__ import annotations

import re
import posixpath
from typing import Any, Callable

from .completion_policy import action_is_read_only, effective_canonical_action


_FILESYSTEM_SCOPE = re.compile(
    r"\b(?:director(?:y|ies)|file(?:s)?|folder(?:s)?|path|tree)\b",
    re.IGNORECASE,
)
_MUTATION = re.compile(
    r"\b(?:apply|change|chmod|modify|set|update)\b",
    re.IGNORECASE,
)
_PERMISSION = re.compile(
    r"\b(?:access\s+mode|file\s+mode|mode|permission(?:s)?)\b",
    re.IGNORECASE,
)


def requests_filesystem_permission_change(instruction: str) -> bool:
    """Return whether an OS instruction explicitly mutates filesystem permissions."""
    normalized = re.sub(r"[-_]+", " ", instruction)
    return bool(
        _FILESYSTEM_SCOPE.search(normalized)
        and _MUTATION.search(normalized)
        and (
            _PERMISSION.search(normalized) or re.search(r"\bchmod\b", normalized, re.I)
        )
    )


def required_actions(domain: str, instruction: str) -> list[str]:
    """Return the atomic discovery and per-file permission actions."""
    if domain != "os" or not requests_filesystem_permission_change(instruction):
        return []
    return ["filesystem.find", "filesystem.set_permissions"]


def requested_scope(state: Any) -> dict[str, Any] | None:
    """Bind a universal permission request to its explicit root and mode."""
    text = str(state.instruction)
    if state.domain != "os" or not requests_filesystem_permission_change(text):
        return None
    if not re.search(r"\b(?:all|every|each)\b.{0,40}\bfiles?\b", text, re.I):
        return None
    modes = set(re.findall(r"(?<![\w.])0?[0-7]{3}(?![\w.])", text))
    if len(modes) != 1:
        return None
    root = None
    paths = re.findall(r'''["'](/[^"'\n]+)["']|(?<!\S)(/[^\s,;]+)''', text)
    named = {a or b for a, b in paths}
    if len(named) == 1:
        root = named.pop().rstrip(".")
    elif not named and re.search(r"\b(?:current|working)\s+(?:directory|folder)\b", text, re.I):
        root = getattr(state, "working_directory", None)
    if not isinstance(root, str) or not root.startswith("/"):
        return {"root": None, "mode": f"{int(next(iter(modes)), 8):04o}", "recursive": True}
    return {"root": posixpath.normpath(root), "mode": f"{int(next(iter(modes)), 8):04o}",
            "recursive": bool(re.search(r"\b(?:tree|recursiv\w*|subdirector\w*)\b", text, re.I))}


def outcome_issues(state: Any, payload: Callable, issue: Callable) -> list[dict[str, Any]]:
    """Prove each target's mode in a complete, fresh native inventory.

    A single-file verifier stays scoped to that file. A final read-only scan
    also certifies files already correct without forcing redundant mutations.
    No host filesystem or evaluator data is consulted.
    """
    spec = requested_scope(state)
    if spec is None:
        return []
    actions = ("filesystem.find", "filesystem.set_permissions")

    def missing(code, target, expected, observed=None, *, step=None, mismatch=False):
        return issue(code, target, expected, observed, actions=actions, step=step, mismatch=mismatch)

    root = spec["root"]
    if root is None:
        return [missing("permissions.scope_unverified", spec, "an observed absolute target directory")]
    events = []
    last_mutation = 0
    for event in state.events:
        kind = event.proposed.get("kind")
        if kind == "gui" and (event.executed or event.validated):
            last_mutation = event.step
        if kind != "adapter":
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        if domain != "os":
            continue
        if not action_is_read_only(action) and (event.executed or event.validated):
            last_mutation = event.step
        if event.executed and not event.error:
            events.append((event, action, args, payload(event)))
    scans = []
    for event, action, args, result in events:
        if action != "filesystem.find":
            continue
        # Exactly the requested root; a child subtree or a filtered basename
        # query cannot replace the universal target set.
        roots = result.get("roots", args.get("roots", []))
        if not isinstance(roots, list) or {posixpath.normpath(p) for p in roots if isinstance(p, str)} != {root}:
            continue
        if set(result.get("name_patterns", args.get("name_patterns", []))) != {"*"}:
            continue
        if result.get("kind", args.get("kind", "file")) not in {"file", "any"}:
            continue
        if spec["recursive"] and result.get("recursive", args.get("recursive", True)) is not True:
            continue
        scans.append((event, result))
    if not scans:
        return [missing("permissions.inventory_missing", spec,
                        "filesystem.find for the entire requested root with name_patterns=['*'], kind=file, "
                        "include_hidden=true and the requested recursion; inspect coverage flags")]
    event, scan = scans[-1]
    matches = scan.get("matches", [])
    complete = (isinstance(matches, list) and scan.get("scan_complete") is True
                and not scan.get("truncated") and not scan.get("context_truncated")
                and not scan.get("matches_omitted") and not scan.get("scan_errors")
                and not scan.get("depth_limited_directories") and not scan.get("skipped_hidden_count")
                and scan.get("match_count") == scan.get("returned_count") == len(matches))
    issues = []
    if not complete:
        issues.append(missing("permissions.inventory_incomplete", spec,
                              "a complete unfiltered inventory; include hidden files, increase max_depth "
                              "for reported unvisited directories and max_results for truncated matches",
                              {k: scan.get(k) for k in ("scan_complete", "truncated", "match_count", "returned_count",
                                                       "matches_omitted", "skipped_hidden_count", "depth_limited_directories", "scan_errors")},
                              step=event.step))
    # Keep useful per-target diagnostics while completing the scan. Only a
    # fresh final inventory can close the gate, even if old mutations succeeded.
    if event.step <= last_mutation:
        issues.append(missing("permissions.final_state_unverified", spec,
                              "a complete filesystem.find after the final mutation", {"after_step": last_mutation},
                              step=event.step))
    observations = {}
    for item in matches if isinstance(matches, list) else []:
        if not isinstance(item, dict) or item.get("kind") != "file" or item.get("is_symlink") is True:
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith(root.rstrip("/") + "/"):
            continue
        mode = item.get("mode")
        if not isinstance(mode, str) or re.fullmatch(r"[0-7]{3,4}", mode) is None:
            mode = None
        observations[path] = {"mode": f"{int(mode, 8):04o}" if mode else None, "step": event.step}
    # A more recent successful single-file readback can clear that target's
    # old mismatch, but it cannot certify the other files or final inventory.
    for later, action, _, result in events:
        path = result.get("path")
        mode = result.get("mode")
        if (later.step > event.step and action == "filesystem.set_permissions" and path in observations
                and isinstance(mode, str) and re.fullmatch(r"[0-7]{3,4}", mode)):
            observations[path] = {"mode": f"{int(mode, 8):04o}", "step": later.step}
    for path, observed in sorted(observations.items()):
        if observed["mode"] != spec["mode"]:
            issues.append(missing("permissions.mode_mismatch" if observed["mode"] else "permissions.mode_unverified",
                                  {"path": path}, {"mode": spec["mode"]}, observed,
                                  step=observed["step"], mismatch=observed["mode"] is not None))
    return issues


__all__ = ["requests_filesystem_permission_change", "required_actions"]
