import json
import pytest
import jsonschema
import chrome_adapter.worker as worker
from chrome_adapter.schema import parse_action_request
from chrome_adapter.errors import AdapterError
from chrome_adapter.atomic_settings import ATOMIC_SETTINGS, ATOMIC_SETTING_SCHEMAS
from integrations.lite_agent.tool_catalog import build_tools,search_actions
from integrations.openapa_osworld.tool_catalog import public_actions

@pytest.mark.parametrize('action',list(ATOMIC_SETTINGS))
def test_one_preference_preserves_unrelated_state_and_is_verified(action,tmp_path,monkeypatch):
    path=tmp_path/'Preferences'
    before={'sentinel':{'nested':[1,2]},'profile':{'unrelated':'kept'}}
    path.write_text(json.dumps(before))
    monkeypatch.setattr(worker,'PREFERENCES',path)
    monkeypatch.setattr(worker,'_with_profile_stopped',lambda callback: callback())
    spec=ATOMIC_SETTING_SCHEMAS[action]['properties']['value']
    value=spec['enum'][0] if 'enum' in spec else (True if spec['type']=='boolean' else (24 if spec['type']=='integer' else 'Example Name'))
    params={'value':value}
    parsed=parse_action_request({'action':action,'params':params})
    result=worker.execute(parsed.to_worker_payload())
    after=json.loads(path.read_text())
    assert after['sentinel']==before['sentinel']
    assert after['profile']['unrelated']=='kept'
    assert result['verification']['passed']
    assert len(result['verification']['checks'])==1
    schema=build_tools('chrome',[action],include_gui=False,include_control_tools=False,strict_generic=True)[0]['function']['parameters']
    jsonschema.validate(params,schema)
    frozen=path.read_bytes()
    for bad in [{**params,'settings':{'font_size':12}},{}]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad,schema)
        with pytest.raises(AdapterError):
            worker.execute({'action':action,'params':bad})
        assert path.read_bytes()==frozen


def test_old_combined_settings_rejected_without_browser_access(monkeypatch):
    assert 'settings.set' not in public_actions('chrome')
    monkeypatch.setattr(worker,'ChromeLifecycle',lambda:pytest.fail('must reject before browser access'))
    with pytest.raises(AdapterError):
        worker.execute({'action':'settings.set','params':{'settings':{'font_size':12}}})
    with pytest.raises(AdapterError):
        parse_action_request({'action':'settings.set','params':{'settings':{'font_size':12}}})

@pytest.mark.parametrize('domain',['chrome','multi_apps'])
def test_font_size_setting_discoverable(domain):
    actions=[m.get('downstream_action',m['action']) for m in search_actions(domain,'chrome font size',strict_generic=True)]
    assert 'settings.set_font_size' in actions
    assert 'settings.set' not in actions
