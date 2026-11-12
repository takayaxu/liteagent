from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from integrations.lite_agent.provider_union_surface import split_discriminated_tools
from integrations.lite_agent.model_client import StructuredToolModelClient, StructuredToolProtocolError


def tools():
    return [{'type': 'function', 'function': {'name': 'gui_action', 'parameters': {'oneOf': [
        {'type': 'object', 'properties': {'action': {'enum': ['click']}, 'x': {'type': 'integer', 'minimum': 0}},
         'required': ['action', 'x'], 'additionalProperties': False},
        {'type': 'object', 'properties': {'action': {'enum': ['type']}, 'text': {'type': 'string'}},
         'required': ['action', 'text'], 'additionalProperties': False}]}}}]


def test_gui_provider_names_identify_operations_without_changing_contracts():
    from integrations.lite_agent.gui_actions import GUI_ACTION_SCHEMA
    original = [{'type': 'function', 'function': {
        'name': 'gui_action', 'parameters': deepcopy(GUI_ACTION_SCHEMA)}}]
    before = deepcopy(original)
    surface, bindings = split_discriminated_tools(original)
    for index, branch in enumerate(GUI_ACTION_SCHEMA['oneOf']):
        action = branch['properties']['action']['enum'][0]
        name = f'gui_action__variant_{index}_{action}'
        assert surface[index]['function']['name'] == name
        assert surface[index]['function']['parameters'] == branch
        assert bindings[name] == {'original_name': 'gui_action', 'schema': branch}
    assert original == before


@pytest.mark.parametrize('args,valid', [({'action': 'click', 'x': 4}, True), ({}, False),
    ({'action': 'click', 'x': -1}, False), ({'action': 'type', 'text': 'hello'}, False),
    ({'action': 'click', 'x': 4, 'text': 'extra'}, False)])
def test_client_restores_only_tool_name_and_keeps_branch_and_original_validation(args, valid):
    original = tools()
    before = deepcopy(original)
    surface, bindings = split_discriminated_tools(original)
    assert original == before
    assert len(surface) == 2
    name = surface[0]['function']['name']
    assert bindings[name]['original_name'] == 'gui_action'
    def create(**request):
        assert 'properties' in request['tools'][0]['function']['parameters']
        return SimpleNamespace(model='Qwen3.5-9B', usage=None, choices=[SimpleNamespace(
            finish_reason='tool_calls', message=SimpleNamespace(reasoning_content='Choose a click.',
                tool_calls=[SimpleNamespace(id='1', function=SimpleNamespace(name=name, arguments=json.dumps(args)))]))])
    client = StructuredToolModelClient(base_url='http://unused', api_key='unused',
        request_timeout_seconds=1, client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    kw = dict(model='Qwen3.5-9B', messages=[], tools=original, temperature=0,
              output_token_budget=512, enable_thinking=True, reasoning_mode='thinking')
    if valid:
        value = client.propose(**kw)
        assert value['tool'] == 'gui_action'
        assert json.loads(value['arguments_raw']) == args
    else:
        with pytest.raises(StructuredToolProtocolError):
            client.propose(**kw)
