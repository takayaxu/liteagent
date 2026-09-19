"""Truthful model-facing constraints derived from a catalog search result."""

from __future__ import annotations

import copy
from typing import Any, Iterable

from integrations.openapa_osworld.tool_catalog import action_signature

from .tool_catalog import DIRECT_ACTION_SCHEMAS, build_tools, tool_name


def _downstream_params_schema(adapter: str, action: str) -> dict[str, Any]:
    if action in DIRECT_ACTION_SCHEMAS.get(adapter, {}):
        downstream_tool = build_tools(
            adapter,
            [action],
            include_gui=False,
            include_control_tools=False,
            strict_generic=True,
        )[0]
        params = copy.deepcopy(downstream_tool["function"]["parameters"])
        description = DIRECT_ACTION_SCHEMAS[adapter][action].get("description")
        if isinstance(description, str) and description:
            params["description"] = description
        return params
    return {
        "type": "object",
        "description": (
            f"Exact params for {adapter}.{action}. Public downstream contract: "
            f"{action_signature(adapter, action)}"
        ),
    }


def _route_payload_schema(
    base_payload_schema: dict[str, Any], adapter: str, action: str
) -> dict[str, Any]:
    payload = copy.deepcopy(base_payload_schema)
    properties = payload.setdefault("properties", {})
    properties["params"] = _downstream_params_schema(adapter, action)
    payload["required"] = ["params"]
    return payload


def constrain_adapter_call_routes(
    tools: list[dict[str, Any]], routes: Iterable[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Limit ``adapter.call`` to exact route pairs returned by tools_search.

    The function changes only the model-visible schema.  It does not choose a
    route, supply a payload, or rewrite a subsequent model call.
    """
    route_pairs = list(dict.fromkeys(routes))
    if not route_pairs:
        return tools

    constrained = copy.deepcopy(tools)
    adapter_call_name = tool_name("adapter.call")
    for tool in constrained:
        function = tool.get("function")
        if not isinstance(function, dict) or function.get("name") != adapter_call_name:
            continue
        parameters = function.get("parameters")
        if not isinstance(parameters, dict):
            continue
        # A later surface pass may apply this helper again (for example the
        # common recovery constraints after completion recovery). Preserve the
        # narrower schema already present instead of widening it back to every
        # route returned by the catalog.
        existing = parameters.get("oneOf")
        if isinstance(existing, list):
            existing_pairs = {
                (
                    branch.get("properties", {}).get("adapter", {}).get("enum", [None])[0],
                    branch.get("properties", {}).get("action", {}).get("enum", [None])[0],
                )
                for branch in existing
                if isinstance(branch, dict)
                and isinstance(branch.get("properties"), dict)
            }
            if existing_pairs:
                route_pairs = [pair for pair in route_pairs if pair in existing_pairs]
        if not route_pairs:
            continue
        payload_schema = parameters.get("properties", {}).get("payload", {})
        parameters["oneOf"] = [
            {
                "properties": {
                    "adapter": {"enum": [adapter]},
                    "action": {"enum": [action]},
                    "payload": _route_payload_schema(payload_schema, adapter, action),
                },
                "required": ["adapter", "action", "payload"],
            }
            for adapter, action in route_pairs
        ]
        pairs = ", ".join(f"{adapter}.{action}" for adapter, action in route_pairs)
        function["description"] += (
            f" Currently available downstream routes: {pairs}."
            " If the needed operation is not listed, call tools_search again; "
            "do not substitute a different listed action."
        )
        break
    return constrained
