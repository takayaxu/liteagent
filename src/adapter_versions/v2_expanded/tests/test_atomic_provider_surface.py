"""A single discovered operation keeps its contract across the provider boundary."""
import copy
import json

import pytest
from jsonschema import Draft202012Validator

from integrations.lite_agent.atomic_tool_surface import (
    atomic_provider_surface, restore_adapter_arguments,
)
from integrations.lite_agent.model_client import (
    StructuredToolModelClient, StructuredToolProtocolError, _qwen_schema_compatible_tools,
)
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools
from test_protocol_recovery import _FakeCompletionClient, _tool_call


def _provider_tools(tools):
    return _qwen_schema_compatible_tools("Qwen3.5-9B", tools)


def wrapper(adapter="os", action="filesystem.find"):
    tools = build_tools("multi_apps", ["adapter.call"], include_gui=False,
                        include_control_tools=False, strict_generic=True)
    return constrain_adapter_call_routes(tools, [(adapter, action)])


def client_call(tools, name, arguments, messages=None):
    fake = _FakeCompletionClient(tool_calls=[_tool_call(json.dumps(arguments), name)],
                                 finish_reason="tool_calls")
    client = StructuredToolModelClient(base_url="http://unused", api_key="unused",
                                      request_timeout_seconds=1, client=fake)
    result = client.propose(model="synthetic", messages=messages or [], tools=tools,
                            temperature=0, output_token_budget=512, enable_thinking=False)
    return result, fake.requests[0]


@pytest.mark.parametrize("system_content", [None, "Existing safety rules.",
    [{"type": "text", "text": "Existing safety rules."}]])
def test_provider_guidance_keeps_system_first_and_original_messages(system_content):
    messages = [{"role": "user", "content": "Find the PDFs."}]
    if system_content is not None:
        messages.insert(0, {"role": "system", "content": system_content})
    before = copy.deepcopy(messages)
    tools = wrapper()
    surface, _ = atomic_provider_surface(tools)
    _, request = client_call(tools, surface[0]["function"]["name"],
        {"roots": ["/tmp"], "name_patterns": ["*.pdf"]}, messages)
    assert messages == before
    assert request["messages"][0]["role"] == "system"
    assert all(m["role"] != "system" for m in request["messages"][1:])
    assert request["messages"][-1] == before[-1]
    if system_content is not None:
        assert "Existing safety rules." in json.dumps(request["messages"][0])


def test_single_action_has_flat_parameters_and_lossless_request_metadata():
    tools = wrapper()
    before = copy.deepcopy(tools)
    surface, bindings = atomic_provider_surface(tools)
    function = surface[0]["function"]
    name = function["name"]
    arguments = {
        "roots": ["/home/user/Downloads"], "name_patterns": ["*.pdf"],
        "request_options": {
            "document": {"url": "file:///tmp/sample.odt"},
            "target": {"window": "chosen-by-model"},
            "verify": [{"type": "synthetic"}], "timeout_ms": 300000,
        },
    }
    assert name.startswith("atomic__os_filesystem_find_")
    assert len(name) <= 64
    assert "payload" not in function["parameters"]["properties"]
    assert Draft202012Validator(function["parameters"]).is_valid(arguments)
    result, request = client_call(tools, name, arguments)
    restored = json.loads(result["arguments_raw"])
    assert restored == restore_adapter_arguments(arguments, bindings[name])
    assert restored["payload"]["verify"] == arguments["request_options"]["verify"]
    assert restored["payload"]["params"] == {key: value for key, value in arguments.items() if key != "request_options"}
    assert result["tool"] == "adapter__adapter_call"
    assert result["provider_tool"] == name
    assert json.loads(result["provider_arguments_raw"]) == arguments
    assert request["tool_choice"] == "required"
    assert tools == before


@pytest.mark.parametrize("alternative", ["propose_done", "fail_task", "gui_action", "tools_search"])
def test_single_adapter_does_not_disable_available_alternatives(alternative):
    tools = wrapper()
    tools.append({"type": "function", "function": {
        "name": alternative, "description": "Synthetic alternative",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }})
    result, request = client_call(tools, alternative, {})
    assert request["tool_choice"] == "required"
    assert result["tool"] == alternative


@pytest.mark.parametrize("arguments", [
    {"roots": ["/tmp"]},
    {"roots": ["/tmp"], "name_patterns": ["*.pdf"], "payload": {}},
    {"roots": ["/tmp"], "name_patterns": ["*.pdf"], "request_options": {"timeout_ms": 1}},
    {"roots": ["/tmp"], "name_patterns": ["*.pdf"], "request_options": {"params": {}}},
])
def test_invalid_atomic_arguments_never_reach_execution(arguments):
    tools = wrapper()
    surface, _ = atomic_provider_surface(tools)
    with pytest.raises(StructuredToolProtocolError, match="do not satisfy"):
        client_call(tools, surface[0]["function"]["name"], arguments)


def test_original_wrapper_constraints_are_checked_after_restoring():
    tools = wrapper()
    tools[0]["function"]["parameters"]["not"] = {
        "properties": {"payload": {"properties": {"params": {
            "properties": {"roots": {"const": ["/blocked"]}}, "required": ["roots"],
        }}, "required": ["params"]}}, "required": ["payload"],
    }
    surface, _ = atomic_provider_surface(tools)
    with pytest.raises(StructuredToolProtocolError, match="do not satisfy"):
        client_call(tools, surface[0]["function"]["name"],
                    {"roots": ["/blocked"], "name_patterns": ["*.pdf"]})


def test_schema_uniqueness_still_enforced_after_wire_conversion():
    tools = wrapper()
    schema = tools[0]["function"]["parameters"]["properties"]["payload"]["properties"]["params"]
    schema["properties"]["roots"]["uniqueItems"] = True
    surface, _ = atomic_provider_surface(tools)
    wire = _provider_tools(surface)[0]["function"]["parameters"]
    assert "uniqueItems" not in wire["properties"]["roots"]
    with pytest.raises(StructuredToolProtocolError, match="do not satisfy"):
        client_call(tools, surface[0]["function"]["name"],
                    {"roots": ["/tmp", "/tmp"], "name_patterns": ["*.pdf"]})


def test_old_route_alias_does_not_enable_a_different_operation():
    tools = wrapper()
    with pytest.raises(StructuredToolProtocolError):
        client_call(tools, "atomic__os_filesystem_remove_fake", {"path": "/tmp/a"})
    with pytest.raises(StructuredToolProtocolError):
        client_call(tools, "adapter_call", {
        "adapter": "os", "action": "filesystem.find",
        "payload": {"params": {"roots": ["/tmp"], "name_patterns": ["*.pdf"]}},
    })


def test_ambiguous_local_routes_retain_original_wrapper():
    tools = build_tools("multi_apps", ["adapter.call"], include_gui=False,
                        include_control_tools=False, strict_generic=True)
    alternatives = constrain_adapter_call_routes(tools, [
        ("os", "filesystem.find"), ("libreoffice_writer", "document.save"),
    ])
    before = copy.deepcopy(alternatives)
    surface, bindings = atomic_provider_surface(alternatives)
    assert bindings == {}
    assert surface == before
    assert alternatives == before


@pytest.mark.parametrize("adapter,action,params", [
    ("os", "image.extract_text_batch", {"input_pattern": "*.pdf", "cwd_source": "explicit", "cwd_path": "/tmp"}),
    ("libreoffice_calc", "range.write", {"sheet": "Sheet1", "range": "A1", "values": [["text"]]}),
    ("libreoffice_writer", "document.save", {}),
])
def test_cross_application_routes_share_same_round_trip(adapter, action, params):
    tools = wrapper(adapter, action)
    surface, bindings = atomic_provider_surface(tools)
    name = surface[0]["function"]["name"]
    assert name in bindings
    result, _ = client_call(tools, name, params)
    restored = json.loads(result["arguments_raw"])
    assert restored["adapter"] == adapter
    assert restored["action"] == action
    assert restored["payload"]["params"] == params


def test_provider_schema_conversion_preserves_keyword_named_properties_and_literals():
    literal = {"const": "literal", "type": ["integer", "string"], "x-route": "literal"}
    schema = {"type": "object", "properties": {
        "const": {"const": literal}, "type": {"type": ["integer", "string"]},
        "x-route": {"type": "string"},
        "object": {"enum": [literal], "default": literal, "examples": [literal]},
    }, "required": ["const", "type", "x-route", "object"], "additionalProperties": False}
    original = copy.deepcopy(schema)
    tools = [{"type": "function", "function": {"name": "synthetic", "parameters": schema}}]
    converted = _provider_tools(tools)[0]["function"]["parameters"]
    assert schema == original
    assert set(converted["properties"]) == set(schema["properties"])
    assert converted["properties"]["const"]["const"] == literal
    assert converted["properties"]["object"] == schema["properties"]["object"]
    valid = {"const": literal, "type": 2, "x-route": "value", "object": literal}
    assert Draft202012Validator(converted).is_valid(valid)
    assert Draft202012Validator(schema).is_valid(valid)


def test_live_inventory_constraints_survive_atomic_description_projection():
    tools = wrapper()
    function = tools[0]["function"]
    function["description"] += " Inventory all direct entries; select the source folder, not its parent."
    params = function["parameters"]["properties"]["payload"]["properties"]["params"]
    params["properties"]["kind"]["enum"] = ["any"]
    params["properties"]["name_patterns"] = {
        "type": "array", "items": {"type": "string", "enum": ["*"]},
        "minItems": 1, "maxItems": 1,
    }
    params["properties"]["recursive"] = {"type": "boolean", "enum": [False]}
    before = copy.deepcopy(tools)
    surface, _ = atomic_provider_surface(tools)
    function = surface[0]["function"]
    assert "select the source folder, not its parent" in function["description"]
    assert 'kind allowed values: ["any"]' in function["description"]
    assert 'name_patterns item allowed values: ["*"]' in function["description"]
    assert "recursive allowed values: [false]" in function["description"]
    valid = {"roots": ["~/Desktop"], "name_patterns": ["*"], "kind": "any", "recursive": False}
    result, _ = client_call(tools, function["name"], valid)
    assert json.loads(result["arguments_raw"])["payload"]["params"] == valid
    with pytest.raises(StructuredToolProtocolError) as error:
        client_call(tools, function["name"], {**valid, "kind": "file"})
    assert any('kind' in hint and 'any' in hint for hint in error.value.schema_hints)
    assert tools == before


def test_organization_inventory_stays_typed_after_precise_broad_catalog_search():
    from types import SimpleNamespace
    from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
    from integrations.lite_agent.state_model import RuntimeState, ExecutionEvent
    state = RuntimeState(task_id="synthetic-invoice-task", domain="multi_apps",
                         instruction='Cross-check the invoices with the bank statements and identify any discrepancies. Then pull out the invoices that don\'t match the statements and put them in the "problematic" folder.')
    routes = ["filesystem.find", "filesystem.rename", "filesystem.copy",
              "filesystem.copy_to_directories", "filesystem.set_permissions",
              "filesystem.create_directory"]
    state.events.append(ExecutionEvent(step=1, timestamp_utc="test", executed=True,
        proposed={"kind": "catalog", "tool": "tools_search", "arguments": {"query": "os.filesystem.find"}},
        result={"status": "ok", "executed": True, "matches": [
            {"adapter": "os", "action": "adapter.call", "tool_name": "adapter__adapter_call", "downstream_action": action,
             "downstream": {"adapter": "os", "action": action}}
            for action in routes]}))
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused"), SimpleNamespace(),
                      model_client=SimpleNamespace(client=None))
    tools = agent.tools(state)
    surface, bindings = atomic_provider_surface(tools)
    assert len(bindings) == 1
    binding = next(iter(bindings.values()))
    assert (binding["adapter"], binding["action"]) == ("os", "filesystem.find")
    params = binding["schema"]
    assert params["properties"]["kind"]["enum"] == ["any"]
    assert params["properties"]["name_patterns"]["items"]["enum"] == ["*"]
    assert params["properties"]["recursive"]["enum"] == [False]
    assert Draft202012Validator(params).is_valid({
        "roots": ["~/Desktop"], "name_patterns": ["*"], "kind": "any", "recursive": False})
