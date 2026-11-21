import jsonschema
import pytest
import vlc_adapter.actions as actions_module
from vlc_adapter.actions import VlcActions, semantic_preference_values
from vlc_adapter.atomic_preferences import ATOMIC_PREFERENCES, ATOMIC_PREFERENCE_SCHEMAS
from vlc_adapter.config import read_config
from vlc_adapter.schema import parse_action_request
from vlc_adapter.errors import AdapterError
from vlc_adapter.worker import _default_specs
from integrations.lite_agent.tool_catalog import build_tools, search_actions
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.openapa_osworld.tool_catalog import public_actions

@pytest.mark.parametrize('action',['config.update','preferences.configure'])
def test_retired_preference_entry_rejected(action,tmp_path,monkeypatch):
    path=tmp_path/'vlcrc'
    path.write_text('unrelated=7\n')
    monkeypatch.setattr(actions_module,'VLC_CONFIG_PATH',path)
    assert action not in public_actions('vlc')
    for call in [lambda: parse_action_request({'action':action,'params':{'values':{'x':1}}}),
                 lambda: VlcActions().dispatch(action,{'values':{'x':1}},1)]:
        with pytest.raises(AdapterError) as error:
            call()
        assert error.value.code == 'UNSUPPORTED_ACTION'
    assert path.read_text() == 'unrelated=7\n'

@pytest.mark.parametrize('action',list(ATOMIC_PREFERENCES))
def test_each_preference_preserves_other_settings_and_has_narrow_schema(action,tmp_path,monkeypatch):
    path=tmp_path/'vlcrc'
    path.write_text('# original comment\nunrelated=7\n')
    monkeypatch.setattr(actions_module,'VLC_CONFIG_PATH',path)
    field=ATOMIC_PREFERENCES[action]
    spec=ATOMIC_PREFERENCE_SCHEMAS[action]['properties']['value']
    value=({'global_play_pause_hotkey':'Media Play Pause','volume_slider_color':'#123456','recording_directory':'/tmp/captures'}.get(field,True if spec['type']=='boolean' else 200))
    params={'value':value}
    parse_action_request({'action':action,'params':params})
    expected=semantic_preference_values({field:value})
    result=VlcActions().dispatch(action,params,1)
    assert result['values'] == expected
    assert read_config(path) == {'unrelated':'7',**expected}
    assert path.read_text().startswith('# original comment\n')
    assert _default_specs(action,params,result)[0]['values'] == expected
    schema=build_tools('vlc',[action],include_gui=False,include_control_tools=False,strict_generic=True)[0]['function']['parameters']
    jsonschema.validate(params,schema)
    frozen=path.read_bytes()
    for bad in [{**params,'values':{'x':1}},{**params,'minimal_interface':False},{}]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad,schema)
        with pytest.raises(AdapterError):
            VlcActions().dispatch(action,bad,1)
        assert path.read_bytes()==frozen

@pytest.mark.parametrize('domain',['vlc','multi_apps'])
@pytest.mark.parametrize('query,action',[
    ('maximum volume percent','preferences.set_maximum_volume_percent'),
    ('recording directory','preferences.set_recording_directory'),
    ('allow multiple instances','preferences.set_allow_multiple_instances')])
def test_preferences_found_and_forwarded(domain,query,action):
    assert action in [m.get('downstream_action',m['action']) for m in search_actions(domain,query,strict_generic=True)]
    tools=constrain_adapter_call_routes(build_tools('multi_apps',['adapter.call'],include_gui=False,strict_generic=True),[('vlc',action)])
    assert tools
