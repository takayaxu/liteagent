"""Publish supported independent-sum semantics before creating a pivot.

The completion gate already checks this contract. Only complete live source
observations may resolve headers; the model still chooses the group, name,
source, destination and placement. Unsupported instructions are unchanged.
"""
from __future__ import annotations

from typing import Any

from .completion_outcomes import _events, _independent_sums, _source
from .instruction_semantics import requested_pivot_count


def constrain_tool(function: dict, state: Any) -> None:
    if getattr(state, "domain", None) != "libreoffice_calc":
        return
    count = requested_pivot_count(state.instruction)
    spec = _independent_sums(state.instruction, count)
    if spec is None:
        return
    source = _source(_events(state), spec)
    if source is None:
        return
    name = function.get("name")
    parameters = function.get("parameters", {})
    if name == "adapter__adapter_call":
        routes = parameters.get("x-allowed-routes", [])
        pairs = {(r.get("adapter"), r.get("action")) for r in routes if isinstance(r, dict)}
        if pairs != {("libreoffice_calc", "pivot.create")}:
            return
        parameters = parameters.get("properties", {}).get("payload", {}).get("properties", {}).get("params", {})
    elif name != "adapter__pivot_create":
        return
    properties = parameters.get("properties", {})
    if not {"row_fields", "column_fields", "page_fields", "data_fields"} <= properties.keys():
        return
    # Same disjoint category form as the percentage contract: Qwen lowering
    # intersects each branch with the complete owner/placement schema.
    parameters["oneOf"] = [{
        "properties": {"row_fields": {"const": [group]}},
        "required": ["row_fields"],
    } for group in source["groups"]]
    for field in ("column_fields", "page_fields"):
        properties[field]["maxItems"] = 0
    measure = properties["data_fields"]
    measure.update(minItems=1, maxItems=1)
    fields = measure["items"]["properties"]
    fields["field"]["const"] = source["measure"]
    fields["aggregation"]["enum"] = ["sum"]
    fields["show_data_as"]["enum"] = ["none"]
    function["description"] += (
        " The requested totals are independent summaries: each pivot groups by ONE "
        "of the observed requested category headers, with the observed measure summed. "
        "A cross-tab or multiple row groups changes this result. Choose which category "
        "to handle from the live inventory. To correct an existing table, retain its "
        "observed name and use replace=true; changing its name creates another table. "
        "Retain already-correct tables and choose disjoint output ranges."
    )
