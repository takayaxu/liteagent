import json
import jsonschema
import pytest
from vscode_adapter.atomic_settings import ATOMIC_SETTINGS, ATOMIC_SETTING_SCHEMAS
from vscode_adapter.actions import VscodeActions
from vscode_adapter.schema import parse_action_request
from vscode_adapter.errors import AdapterError
from vscode_adapter.worker import _default_specs
from integrations.lite_agent.tool_catalog import build_tools, search_actions
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.vscode_configuration_semantics import required_actions
from integrations.openapa_osworld.tool_catalog import public_actions

RETIRED = ['debugging.configure', 'editor.configure', 'files.configure', 'settings.update']

@pytest.mark.parametrize('action', RETIRED)
def test_legacy_settings_are_not_public_or_executable(action, tmp_path):
    path = tmp_path/'settings.json'
    path.write_text('{"sentinel": true}')
    assert action not in public_actions('vs_code')
    for call in [lambda: parse_action_request({'action': action, 'params': {'path': str(path), 'values': {'x': 1}}}),
                 lambda: VscodeActions().dispatch(action, {'path': str(path), 'values': {'x': 1}}, 1)]:
        with pytest.raises(AdapterError) as error:
            call()
        assert error.value.code == 'UNSUPPORTED_ACTION'
    assert path.read_text() == '{"sentinel": true}'

@pytest.mark.parametrize('action', list(ATOMIC_SETTINGS))
def test_each_single_setting_preserves_other_values_and_rejects_combinations(action, tmp_path):
    key, choices = ATOMIC_SETTINGS[action]
    spec = ATOMIC_SETTING_SCHEMAS[action]['properties']['value']
    value = spec['enum'][0] if 'enum' in spec else (True if spec['type'] == 'boolean' else spec.get('minimum', 1))
    expected = choices[value] if choices is not None else value
    path = tmp_path/'settings.json'
    before = {'unrelated': {'nested': [1,2,3]}, 'editor.fontSize': 13}
    path.write_text(json.dumps(before))
    params = {'path': str(path), 'value': value}
    parsed = parse_action_request({'action': action, 'params': params})
    result = VscodeActions().dispatch(action, parsed.params, 1)
    assert json.loads(path.read_text()) == {**before, key: expected}
    assert result['values'] == {key: expected}
    assert _default_specs(action, params, result)[0]['expected'] == {key: expected}
    schema = build_tools('vs_code', [action], include_gui=False, include_control_tools=False, strict_generic=True)[0]['function']['parameters']
    jsonschema.validate(params, schema)
    frozen = path.read_bytes()
    for bad in [{**params,'values':{'another': 1}}, {**params,'auto_save': 'off'}, {'path':str(path)}]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
        with pytest.raises(AdapterError):
            VscodeActions().dispatch(action,bad,1)
        assert path.read_bytes() == frozen

@pytest.mark.parametrize('query,action', [
    ('wrap tabs','editor.set_wrap_tabs'),
    ('word wrap column','editor.set_word_wrap_column'),
    ('focus editor on break','debugging.set_focus_editor_on_break'),
    ('auto save delay','files.set_auto_save_delay_ms')])
@pytest.mark.parametrize('domain', ['vs_code','multi_apps'])
def test_atomic_action_discoverable_and_forwardable(domain,query,action):
    matches=search_actions(domain,query,strict_generic=True)
    assert action in [m.get('downstream_action',m['action']) for m in matches]
    tools=constrain_adapter_call_routes(build_tools('multi_apps',['adapter.call'],include_gui=False,strict_generic=True),[('vs_code',action)])
    assert action in json.dumps(tools)
    assert not set(RETIRED).intersection(public_actions('vs_code'))


def test_autosave_instruction_requires_distinct_actions():
    required=required_actions('vs_code','Set automatic saving after a delay of 500 ms')
    assert 'files.set_auto_save' in required
    assert 'files.set_auto_save_delay_ms' in required
    assert required_actions('vs_code','Set editor.wordWrapColumn to 50') == ['editor.set_word_wrap_column']


def test_simple_setting_instruction_does_not_require_unrelated_mutations():
    assert required_actions('vs_code','Wrap tabs onto multiple rows') == ['editor.set_wrap_tabs']
    assert required_actions('vs_code','Do not focus the editor on debugger break') == ['debugging.set_focus_editor_on_break']
