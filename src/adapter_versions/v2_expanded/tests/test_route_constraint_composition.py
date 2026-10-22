from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator

from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools


FIND = ("os", "filesystem.find")
RENAME = ("os", "filesystem.rename")


def _tools(routes):
    return constrain_adapter_call_routes(
        build_tools(
            "multi_apps", ["adapter.call"], include_gui=False,
            include_control_tools=True, strict_generic=True,
        ),
        routes,
    )


def _parameters(tools):
    return next(
        tool["function"]["parameters"] for tool in tools
        if tool["function"]["name"] == "adapter__adapter_call"
    )


def test_broader_pass_preserves_single_route_and_parameter_constraints():
    tools = _tools([FIND])
    schema = _parameters(tools)
    params = schema["properties"]["payload"]["properties"]["params"]
    params["properties"]["kind"]["enum"] = ["any"]
    params["properties"]["recursive"] = {"type": "boolean", "enum": [False]}
    before = copy.deepcopy(tools)

    constrained = constrain_adapter_call_routes(tools, [RENAME, FIND])

    assert constrained == before
    assert tools == before
    schema = _parameters(constrained)
    Draft202012Validator.check_schema(schema)
    arguments = {
        "adapter": "os", "action": "filesystem.find",
        "payload": {"params": {
            "roots": ["~/Desktop"], "name_patterns": ["*"],
            "kind": "any", "recursive": False,
        }},
    }
    validator = Draft202012Validator(schema)
    validator.validate(arguments)
    arguments["payload"]["params"]["kind"] = "file"
    assert not validator.is_valid(arguments)


def test_flat_single_route_without_metadata_is_not_widened():
    tools = _tools([FIND])
    del _parameters(tools)["x-allowed-routes"]
    params = _parameters(tools)["properties"]["payload"]["properties"]["params"]
    params["properties"]["kind"]["enum"] = ["any"]

    schema = _parameters(constrain_adapter_call_routes(tools, [FIND, RENAME]))

    assert schema["x-allowed-routes"] == [{"adapter": "os", "action": "filesystem.find"}]
    assert schema["properties"]["payload"]["properties"]["params"] == params


def test_exact_pair_metadata_does_not_authorize_cross_product():
    routes = [("chrome", "settings.set"), ("libreoffice_impress", "presentation.inspect")]
    tools = _tools(routes)
    constrained = constrain_adapter_call_routes(
        tools, [*routes, ("libreoffice_impress", "settings.set")]
    )
    assert constrained == tools
    assert _parameters(constrained)["x-allowed-routes"] == [
        {"adapter": adapter, "action": action} for adapter, action in routes
    ]


def test_narrowing_multiple_routes_restores_detailed_params():
    schema = _parameters(constrain_adapter_call_routes(_tools([FIND, RENAME]), [FIND]))
    assert schema["x-allowed-routes"] == [{"adapter": "os", "action": "filesystem.find"}]
    assert "roots" in schema["properties"]["payload"]["properties"]["params"]["required"]


@pytest.mark.parametrize("empty_allowlist", [False, True])
def test_empty_route_intersection_exposes_no_adapter_call(empty_allowlist):
    tools = _tools([FIND])
    if empty_allowlist:
        _parameters(tools)["x-allowed-routes"] = []
    constrained = constrain_adapter_call_routes(tools, [RENAME])
    assert {tool["function"]["name"] for tool in constrained} == {
        "tools_search", "propose_done", "fail_task",
    }
