"""Compare explicit axis roles with native chart sources; never construct a chart."""
from __future__ import annotations

import re

from .calc_chart_outcomes import ACTIONS, _read, _source_range
from .completion_outcomes import _issue
from .instruction_semantics import requested_chart_count


def _label(value):
    return " ".join(str(value).strip().casefold().split())


def _contains(outer, inner):
    if not outer or not inner or outer[0] != inner[0]:
        return False
    a, b = outer[1], inner[1]
    return (a[0] == b[0] == a[2] == b[2] and a[1] <= b[1] <= b[3] <= a[3]
            or a[1] == b[1] == a[3] == b[3] and a[0] <= b[0] <= b[2] <= a[2])


def _request(instruction, fields):
    fields = set(fields) | {_label(m[1]) for m in re.finditer(
        r"[\"'“]([^\"'“”]+)[\"'”]\s+(?:column\s+)?(?:on|as)\s+(?:the\s+)?[xy][- ]?axis\b",
        instruction, re.I)}
    requested = []
    for axis in ("x", "y"):
        hits = set()
        for field in fields:
            pattern = (rf"(?<!\w)[\"'“”]?{re.escape(field)}[\"'“”]?\s+"
                       rf"(?:column\s+)?(?:on|as)\s+(?:the\s+)?{axis}[- ]?axis\b")
            for match in re.finditer(pattern, instruction, re.I):
                # A clause naming several fields needs a multi-field contract.
                prefix = re.split(r"[.!?]|\b[xy][- ]?axis\b", instruction[:match.start()], flags=re.I)[-1]
                if any(other != field and re.search(rf"(?<!\w){re.escape(other)}(?!\w).*?(?:\b(?:and|or|plus|with|versus|against)\b|[,&/])", prefix, re.I)
                       for other in fields):
                    continue
                hits.add(field)
        if len(hits) != 1:
            return None
        requested.append(hits.pop())
    return tuple(requested) if requested[0] != requested[1] else None


def _identities(chart, observations, default_sheet):
    records = []
    # A native series label is evidence tied to its actual plotted source.
    for series in chart.get("data_series", []):
        labels, ranges = series.get("labels"), series.get("source_ranges")
        if (isinstance(labels, list) and len(labels) == 1 and isinstance(labels[0], str)
                and labels[0].strip() and isinstance(ranges, list) and len(ranges) == 1):
            if source := _source_range(ranges[0], default_sheet):
                records.append((_label(labels[0]), source))
    # Read the header actually selected by the chart, not a guessed row above
    # a data-only selection. Both row and column series layouts are legal.
    for area in chart.get("source_ranges", []):
        parsed = _source_range(area, default_sheet)
        if not parsed:
            continue
        sheet, rect = parsed
        if chart.get("column_headers") is True and rect[0] == rect[2]:
            header = (sheet, (rect[0], rect[1], rect[0], rect[1]))
        elif chart.get("row_headers") is True and rect[1] == rect[3]:
            header = (sheet, (rect[0], rect[1], rect[0], rect[1]))
        else:
            continue
        values = _read(header, observations)
        if values and isinstance(values[0], str) and values[0].strip():
            records.append((_label(values[0]), parsed))
    return records


def axis_issues(instruction, chart, sheet, observations, step):
    """Only singular, explicit X/Y fields on categorical Cartesian charts."""
    if (requested_chart_count(instruction) != 1
            or chart.get("type") not in {"line", "column", "area"}
            or re.search(r"\b(?:combo|combination|combined|secondary|right[- ]axis|dual[- ]axis)\b", instruction, re.I)):
        return []
    series, axes = chart.get("data_series"), chart.get("category_axes")
    if not isinstance(series, list) or not isinstance(axes, list):
        return []  # Existing native-inventory check handles absent evidence.
    if len(axes) > 1 or any(s.get("coordinate_system", 0) != 0 for s in [*series, *axes]):
        return []
    records = _identities(chart, observations, chart.get("source_sheet", sheet))
    spec = _request(instruction, {label for label, _ in records})
    if spec is None:
        return []
    target = {"sheet": sheet, "name": chart.get("name")}
    expected = {"x_category_field": spec[0], "y_value_field": spec[1]}
    observed = {"category_axes": axes, "data_series": series}
    if (chart.get("data_series_inspect_error") or chart.get("data_series_omitted_from_context")
            or chart.get("category_axes_omitted_from_context")
            or chart.get("data_series_count", len(series)) != len(series)
            or any(s.get(k) for s in series for k in ("labels_omitted_from_context",
                   "source_ranges_omitted_from_context", "inspect_error"))):
        return [_issue("charts.axis_roles_unverified", target, expected, observed, actions=ACTIONS, step=step)]
    if not axes:
        return [_issue("charts.axis_roles_mismatch", target, expected, observed,
                       actions=ACTIONS, step=step, mismatch=True)]

    def identity(area):
        parsed = _source_range(area, chart.get("source_sheet", sheet))
        return {label for label, source in records if _contains(source, parsed)}

    category_names = identity(axes[0].get("source_range"))
    value_names = []
    for item in series:
        ranges = item.get("source_ranges")
        value_names.append(identity(ranges[0]) if isinstance(ranges, list) and len(ranges) == 1 else set())
    if not category_names or not value_names or any(not names for names in value_names):
        return [_issue("charts.axis_roles_unverified", target, expected,
                       {**observed, "needed": "read selected source headers to identify categories and value fields"},
                       actions=ACTIONS, step=step)]
    if len(category_names) > 1 or any(len(names) > 1 for names in value_names):
        return [_issue("charts.axis_roles_unverified", target, expected, observed, actions=ACTIONS, step=step)]
    if category_names != {spec[0]} or any(names != {spec[1]} for names in value_names):
        return [_issue("charts.axis_roles_mismatch", target, expected, observed,
                       actions=ACTIONS, step=step, mismatch=True)]
    return []
