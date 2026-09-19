from __future__ import annotations

import jsonschema
import pytest

from integrations.lite_agent.tool_catalog import DIRECT_ACTION_SCHEMAS, build_tools
from os_adapter.actions import OSActions
from os_adapter.errors import AdapterError
from os_adapter.schema import validate_action_params
from os_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS


ACTION = "desktop.set_setting"
BASE_ARGUMENTS = {"schema": "org.example.Settings", "key": "sample"}


def _exposed_schema() -> dict:
    tools = build_tools(
        "os",
        [ACTION],
        include_gui=False,
        include_control_tools=False,
        strict_generic=True,
    )
    return tools[0]["function"]["parameters"]


def test_desktop_setting_contract_is_owned_by_os_manifest() -> None:
    manifest = STRICT_ACTION_PARAM_SCHEMAS[ACTION]
    direct = DIRECT_ACTION_SCHEMAS["os"][ACTION]

    # The LiteAgent catalog must consume the Adapter-owned contract verbatim.
    assert direct == manifest
    value_schema = manifest["properties"]["value"]
    assert "oneOf" not in value_schema
    assert value_schema["anyOf"] == [
        {"type": "string"},
        {"type": "boolean"},
        {"type": "number"},
    ]

    exposed = _exposed_schema()
    jsonschema.Draft202012Validator.check_schema(exposed)
    assert exposed["properties"]["value"] == value_schema


@pytest.mark.parametrize("value", [132, 132.0, 1.25, "true", True])
def test_desktop_setting_accepts_scalar_values_without_numeric_overlap(value) -> None:
    arguments = {**BASE_ARGUMENTS, "value": value}

    # Both the model-visible boundary and the Adapter's runtime contract agree.
    assert not list(
        jsonschema.Draft202012Validator(_exposed_schema()).iter_errors(arguments)
    )
    validate_action_params(ACTION, arguments)


@pytest.mark.parametrize("value", [None, [], {}, ["a", "b"]])
def test_desktop_setting_rejects_non_scalar_values(value) -> None:
    arguments = {**BASE_ARGUMENTS, "value": value}
    errors = list(
        jsonschema.Draft202012Validator(_exposed_schema()).iter_errors(arguments)
    )
    assert errors
    with pytest.raises(AdapterError, match="value must be a scalar"):
        validate_action_params(ACTION, arguments)


def test_desktop_setting_explains_instance_paths_and_key_discovery() -> None:
    exposed = _exposed_schema()["properties"]

    assert "SCHEMA:/instance/path/" in exposed["schema"]["description"]
    assert "not a filesystem path" in exposed["schema"]["description"]
    assert "gsettings list-keys SCHEMA[:PATH]" in exposed["key"]["description"]
    assert "different schema" in exposed["key"]["description"]


@pytest.mark.parametrize(
    "schema",
    ["org.example.Settings", "org.example.Profile:/org/example/profiles/observed/"],
)
def test_desktop_setting_preserves_selected_schema_and_instance_path(schema) -> None:
    class Runner:
        def __init__(self):
            self.calls = []

        def run(self, argv, **kwargs):
            self.calls.append(argv)
            return {"stdout": "1.25\n", "returncode": 0}

    arguments = {"schema": schema, "key": "sample-scale", "value": 1.25}
    jsonschema.validate(arguments, _exposed_schema())
    validate_action_params(ACTION, arguments)
    runner = Runner()

    result = OSActions(runner=runner).set_setting(arguments, 5)

    assert runner.calls == [
        ["gsettings", "set", schema, "sample-scale", "1.25"],
        ["gsettings", "get", schema, "sample-scale"],
    ]
    assert result == {
        "schema": schema,
        "key": "sample-scale",
        "expected": "1.25",
        "observed": "1.25",
    }
