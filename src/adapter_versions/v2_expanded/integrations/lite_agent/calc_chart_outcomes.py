"""Check native chart source boundaries without choosing or editing model ranges."""
from __future__ import annotations

import re

from .completion_outcomes import _issue, _same_document, rectangle
from .completion_policy import action_is_read_only, action_is_save

ACTIONS = ("workbook.inspect", "range.read", "chart.create", "workbook.save")


def _source_range(value, default_sheet):
    match = re.fullmatch(r"(?:\$?(?:'((?:[^']|'')+)'|([^.!]+))[.!])?(.+)", str(value or ""))
    if not match:
        return None
    sheet = (match[1] or match[2] or default_sheet or "").replace("''", "'")
    rect = rectangle(match[3])
    if not sheet or not rect or (rect[2] - rect[0] + 1) * (rect[3] - rect[1] + 1) > 4096:
        return None
    if rect[0] != rect[2] and rect[1] != rect[3]:
        return None  # Multi-level categories need a different interpretation.
    return sheet, rect


def _observations(events):
    reads = []
    for event, action, args, payload in events:
        if not action_is_read_only(action) and not action_is_save(action):
            if action.removeprefix("uncertain:") not in {"chart.create", "sheet.create"}:
                reads = []  # GUI/uncertain edits can change cells or formula results.
        if action != "range.read" or not _same_document(events, event, payload):
            continue
        rect = rectangle(args.get("range"))
        values = payload.get("values")
        if (not rect or not args.get("sheet")
                or payload.get("sheet", args["sheet"]) != args["sheet"]
                or rectangle(payload.get("range", args.get("range"))) != rect
                or any(payload.get(k) for k in ("truncated", "context_truncated", "source_truncated"))
                or not isinstance(values, list) or len(values) != rect[3] - rect[1] + 1
                or any(not isinstance(row, list) or len(row) != rect[2] - rect[0] + 1 for row in values)):
            continue
        # A newer overlapping read supersedes older evidence even if it only
        # covers a small part of an earlier rectangle.
        reads = [(name, area, matrix, step) for name, area, matrix, step in reads
                 if name != args["sheet"] or area[2] < rect[0] or rect[2] < area[0]
                 or area[3] < rect[1] or rect[3] < area[1]]
        reads.append((args["sheet"], rect, values, event.step))
    return reads


def _read(parsed, observations):
    if not parsed:
        return None
    sheet, rect = parsed
    for name, area, values, step in reversed(observations):
        if (name == sheet and area[0] <= rect[0] and area[1] <= rect[1]
                and area[2] >= rect[2] and area[3] >= rect[3]):
            return [values[r - area[1]][c - area[0]]
                    for r in range(rect[1], rect[3] + 1) for c in range(rect[0], rect[2] + 1)]
    return None


def _blank(value):
    return value is None or isinstance(value, str) and not value.strip()


def _aligned(category, values):
    if category[0] != values[0]:
        return True  # Different sheet layouts may legitimately use different offsets.
    a, b = category[1], values[1]
    if a[0] == a[2] and b[0] == b[2]:
        return a[3] < b[1] or b[3] < a[1] or (a[1] == b[1] and a[3] == b[3])
    if a[1] == a[3] and b[1] == b[3]:
        return a[2] < b[0] or b[2] < a[0] or (a[0] == b[0] and a[2] == b[2])
    return True


def source_issues(state, events, objects, step):
    """Called only with the final complete inventory of requested new charts."""
    observations = _observations(events)
    # An explicit request for blank categories owns their interpretation.
    keep_blanks = bool(re.search(r"\b(?:include|retain|keep|preserve)\b[^.!?]*\b(?:blank|empty|missing)\b",
                                 state.instruction, re.I))
    issues = []
    for sheet, chart in objects:
        if chart.get("type") not in {"bar", "column", "line", "area", "pie"}:
            continue
        axes, series = chart.get("category_axes"), chart.get("data_series")
        target = {"sheet": sheet, "name": chart.get("name")}
        if (not isinstance(axes, list) or not isinstance(series, list) or chart.get("data_series_inspect_error")
                or chart.get("data_series_omitted_from_context")):
            issues.append(_issue("charts.source_unverified", target, "native categories and value series",
                                 None, actions=ACTIONS, step=step))
            continue
        if len(axes) != 1:
            continue  # Multiple coordinate systems/automatic categories are unsupported.
        default = chart.get("source_sheet", sheet)
        category = _source_range(axes[0].get("source_range"), default)
        labels = _read(category, observations)
        sources, plotted = [], []
        complete = labels is not None and bool(series)
        for item in series:
            ranges = item.get("source_ranges")
            if not isinstance(ranges, list) or len(ranges) != 1:
                complete = False
                continue
            parsed = _source_range(ranges[0], default)
            values = _read(parsed, observations)
            if values is None:
                complete = False
            sources.append(parsed)
            plotted.append(values)
        observed = {"category_range": axes[0].get("source_range"),
                    "value_ranges": [item.get("source_ranges") for item in series]}
        if not complete:
            issues.append(_issue("charts.source_unverified", target,
                                 "current complete range.read covering the observed category and value ranges",
                                 observed, actions=ACTIONS, step=step))
            continue
        if any(len(values) != len(labels) for values in plotted):
            issues.append(_issue("charts.source_length_mismatch", target, "equal category/value lengths per series",
                                 {**observed, "category_count": len(labels),
                                  "series_counts": [len(v) for v in plotted]},
                                 actions=ACTIONS, step=step, mismatch=True))
            continue
        if any(not _aligned(category, source) for source in sources):
            issues.append(_issue("charts.source_alignment_mismatch", target,
                                 "category and value ranges aligned to the same source observations",
                                 observed, actions=ACTIONS, step=step, mismatch=True))
        if keep_blanks or len(labels) < 2:
            continue
        for edge, index in (("first", 0), ("last", len(labels) - 1)):
            if not _blank(labels[index]) or not any(not _blank(v) for v in labels):
                continue
            empty_values = all(_blank(values[index]) for values in plotted)
            # Entirely empty edge observations are an unused boundary. A missing
            # label with real values may be intentional: report uncertainty.
            issues.append(_issue(
                "charts.blank_source_boundary" if empty_values else "charts.blank_category_unverified",
                target,
                "exclude empty boundary observations from plotted ranges" if empty_values
                else "category identity or explicit instruction to retain an unnamed category",
                {**observed, "edge": edge, "category": labels[index],
                 "series_values": [values[index] for values in plotted]},
                actions=ACTIONS, step=step, mismatch=empty_values,
            ))
    return issues
