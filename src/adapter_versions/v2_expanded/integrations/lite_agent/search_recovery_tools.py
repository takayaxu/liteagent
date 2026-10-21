"""Truthful model-facing constraints derived from a catalog search result."""

from __future__ import annotations

import copy
import logging
from typing import Any, Iterable

from integrations.openapa_osworld.tool_catalog import action_signature, public_actions

from .tool_catalog import DIRECT_ACTION_SCHEMAS, build_tools, tool_name


_LOGGER = logging.getLogger(__name__)


def _is_public_route(adapter: str, action: str) -> bool:
    try:
        return action in public_actions(adapter)
    except ValueError:
        return False


def _downstream_params_schema(adapter: str, action: str) -> dict[str, Any]:
    if not _is_public_route(adapter, action):
        raise ValueError(f"Unregistered public Adapter route: {adapter}.{action}")
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
        "properties": {},
        "required": [],
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


def _flat_route_description(adapter: str, action: str) -> str:
    """Summarize a route without embedding a branch-heavy union schema."""
    schema = _downstream_params_schema(adapter, action)
    required = schema.get("required", [])
    fields: list[str] = []
    for name, field in schema.get("properties", {}).items():
        if not isinstance(field, dict):
            continue
        detail = field.get("description")
        if not isinstance(detail, str) or not detail:
            if isinstance(field.get("enum"), list):
                detail = "choose one of " + ", ".join(map(str, field["enum"]))
            elif field.get("type"):
                detail = str(field["type"])
        if isinstance(detail, str) and detail:
            fields.append(f"{name}: {detail[:240]}")
    required_text = ", ".join(map(str, required)) or "none"
    overview = schema.get("description")
    overview_text = f" {overview[:1000]}" if isinstance(overview, str) else ""
    return (
        f"{adapter}.{action} requires [{required_text}]. "
        + overview_text
        + " "
        + " ".join(fields[:8])
    )


def constrain_adapter_call_routes(
    tools: list[dict[str, Any]], routes: Iterable[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Limit ``adapter.call`` to exact route pairs returned by tools_search.

    The function changes only the model-visible schema.  It does not choose a
    route, supply a payload, or rewrite a subsequent model call.
    """
    requested_pairs = list(dict.fromkeys(routes))
    if not requested_pairs:
        return tools

    constrained = copy.deepcopy(tools)
    adapter_call_name = tool_name("adapter.call")
    route_pairs = [pair for pair in requested_pairs if _is_public_route(*pair)]
    invalid_pairs = [pair for pair in requested_pairs if pair not in route_pairs]
    if invalid_pairs:
        diagnostic = (
            "Route configuration error: unregistered public Adapter route(s): "
            + ", ".join(f"{adapter}.{action}" for adapter, action in invalid_pairs)
            + ". These routes are not callable and have not been replaced. "
            "Use tools_search to discover a registered public action."
        )
        _LOGGER.error(diagnostic)
        search = next(
            (
                tool for tool in constrained
                if tool.get("function", {}).get("name") == "tools_search"
            ),
            None,
        )
        if search is None:
            search = next(
                tool for tool in build_tools(
                    "multi_apps", [], include_gui=False,
                    include_control_tools=True, strict_generic=True,
                )
                if tool.get("function", {}).get("name") == "tools_search"
            )
            constrained.append(search)
        search["function"]["description"] += " " + diagnostic
        if not route_pairs:
            return [
                tool for tool in constrained
                if tool.get("function", {}).get("name") != adapter_call_name
            ]
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
        if len(route_pairs) == 1:
            # A single discovered route does not need a union. Flattening it
            # avoids making small tool-calling models emit an empty object when
            # they cannot satisfy a nested oneOf branch, while preserving the
            # exact adapter/action/payload contract.
            adapter, action = route_pairs[0]
            parameters.pop("oneOf", None)
            parameters["properties"]["adapter"] = {
                "type": "string",
                "enum": [adapter],
            }
            parameters["properties"]["action"] = {
                "type": "string",
                "enum": [action],
            }
            parameters["properties"]["payload"] = _route_payload_schema(
                payload_schema, adapter, action
            )
            parameters["required"] = ["adapter", "action", "payload"]
        else:
            # A union of nested downstream schemas is faithful JSON Schema but
            # is not reliably emitted by the small tool-calling models used by
            # this runner: once two routes are visible they commonly produce
            # an empty object instead of selecting a branch. Keep the route
            # selection explicit and let the owning Adapter validate the
            # action-specific params after dispatch.
            adapters = list(dict.fromkeys(adapter for adapter, _ in route_pairs))
            actions = list(dict.fromkeys(action for _, action in route_pairs))
            parameters.pop("oneOf", None)
            parameters["properties"]["adapter"] = {
                "type": "string",
                "enum": adapters,
            }
            parameters["properties"]["action"] = {
                "type": "string",
                "enum": actions,
            }
            parameters["properties"]["payload"] = copy.deepcopy(payload_schema)
            parameters["properties"]["payload"]["required"] = ["params"]
            route_help = "; ".join(
                _flat_route_description(adapter, action)
                for adapter, action in route_pairs
            )
            parameters["properties"]["payload"]["properties"]["params"] = {
                "type": "object",
                "description": (
                    "Action-specific params for the selected adapter/action. "
                    + route_help
                ),
            }
            parameters["required"] = ["adapter", "action", "payload"]
        # Preserve the exact adapter/action pairing for protocol diagnostics.
        # The flattened public schema intentionally uses separate enums for
        # model compatibility, so recovering from those enums alone would
        # incorrectly imply a Cartesian product of routes.
        parameters["x-allowed-routes"] = [
            {"adapter": adapter, "action": action}
            for adapter, action in route_pairs
        ]
        # Ask OpenAI-compatible providers to enforce this live schema during
        # generation.  The client-side route check below remains authoritative
        # for providers that ignore the optional strict hint.
        function["strict"] = True
        pairs = ", ".join(f"{adapter}.{action}" for adapter, action in route_pairs)
        has_search_control = any(
            isinstance(candidate.get("function"), dict)
            and candidate["function"].get("name") == "tools_search"
            for candidate in constrained
        )
        route_lease_guidance = (
            " If the needed operation is not listed, call tools_search again; "
            "do not substitute a different listed action."
            if has_search_control
            else (
                " This route lease is closed for this turn; call only one of the "
                "listed routes and do not emit or search for another action."
            )
        )
        function["description"] += (
            f" Currently available downstream routes: {pairs}."
            + route_lease_guidance
        )
        if route_pairs == [("libreoffice_calc", "workbook.save")]:
            function["description"] += (
                " The table mutation has already been read back successfully. "
                "This is the only permitted next operation; call workbook.save "
                "now with an empty params object. Do not repeat PDF extraction, "
                "range.read, or range.write."
            )
        break
    return constrained
