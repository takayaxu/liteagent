from __future__ import annotations

from copy import deepcopy

import jsonschema
import pytest

from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools
from os_adapter.errors import AdapterError
from os_adapter.schema import validate_action_params


ACTION = "archive.create_extract"


def _schema(wrapped: bool) -> dict:
    if not wrapped:
        return build_tools(
            "os",
            [ACTION],
            include_gui=False,
            include_control_tools=False,
            strict_generic=True,
        )[0]["function"]["parameters"]
    tools = constrain_adapter_call_routes(
        build_tools(
            "multi_apps", ["adapter.call"], include_gui=False, strict_generic=True
        ),
        [("os", ACTION)],
    )
    function = next(
        tool["function"]
        for tool in tools
        if tool["function"]["name"] == "adapter__adapter_call"
    )
    return function["parameters"]["oneOf"][0]["properties"]["payload"]["properties"][
        "params"
    ]


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize(
    "mode,field,value",
    [
        (
            "create",
            "input_paths",
            ["/tmp/synthetic-notes.txt", "/tmp/synthetic-chart.csv"],
        ),
        ("extract", "destination_directory", "/tmp/synthetic-unpacked"),
    ],
)
def test_archive_branches_are_complete_for_tool_grammar(
    wrapped: bool,
    mode: str,
    field: str,
    value: object,
) -> None:
    schema = _schema(wrapped)
    branch = next(
        item for item in schema["oneOf"] if item["properties"]["mode"]["const"] == mode
    )
    assert branch["type"] == "object"
    assert branch["additionalProperties"] is False
    assert set(branch["required"]) == {"mode", "archive_path", field}
    assert branch["properties"]["archive_path"] == schema["properties"]["archive_path"]
    assert branch["properties"][field] == schema["properties"][field]
    params = {"mode": mode, "archive_path": "/tmp/synthetic-bundle.zip", field: value}
    before = deepcopy(params)
    jsonschema.validate(params, branch)
    jsonschema.validate(params, schema)
    validate_action_params(ACTION, params)
    assert params == before


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("mode", ["create", "extract"])
def test_archive_incomplete_call_stays_invalid_in_each_branch(
    wrapped: bool, mode: str
) -> None:
    schema = _schema(wrapped)
    params = {"mode": mode}
    assert not jsonschema.Draft202012Validator(schema).is_valid(params)
    branch = next(
        item for item in schema["oneOf"] if item["properties"]["mode"]["const"] == mode
    )
    assert not jsonschema.Draft202012Validator(branch).is_valid(params)
    with pytest.raises(AdapterError):
        validate_action_params(ACTION, params)


@pytest.mark.parametrize("wrapped", [False, True])
def test_archive_optional_fields_keep_their_contract(wrapped: bool) -> None:
    params = {
        "mode": "create",
        "archive_path": "~/synthetic-bundle.ZIP",
        "input_paths": ["~/synthetic-notes.txt"],
        "base_directory": "~/",
        "overwrite": True,
    }
    before = deepcopy(params)
    jsonschema.validate(params, _schema(wrapped))
    validate_action_params(ACTION, params)
    assert params == before
