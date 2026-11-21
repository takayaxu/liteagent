import pytest
import jsonschema
from integrations.lite_agent.tool_catalog import build_tools, search_actions
from integrations.openapa_osworld.tool_catalog import public_actions
from os_adapter.actions import OSActions
from os_adapter.errors import AdapterError
from os_adapter.schema import parse_action_request, validate_action_params
from os_adapter.worker import _default_specs

RETIRED = ['desktop.set_accessibility_scale', 'desktop.set_dim_inactive']

@pytest.mark.parametrize('action', RETIRED)
def test_combined_desktop_action_is_absent_and_rejected(action):
    assert action not in public_actions('os')
    for call in [lambda: parse_action_request({'action': action, 'params': {}}),
                 lambda: validate_action_params(action, {}),
                 lambda: OSActions().dispatch(action, {}, 1)]:
        with pytest.raises(AdapterError) as error:
            call()
        assert error.value.code == 'UNSUPPORTED_ACTION'

@pytest.mark.parametrize('query', ['increase text size accessibility', 'dim inactive screen'])
@pytest.mark.parametrize('domain', ['os', 'multi_apps'])
def test_single_setting_is_discoverable(domain, query):
    candidates = search_actions(domain, query, strict_generic=True)
    actions = [item.get('downstream_action', item['action']) for item in candidates]
    assert 'desktop.set_setting' in actions[:3]
    assert not set(RETIRED).intersection(actions)

@pytest.mark.parametrize('extra', [{'idle_delay': 60}, {'settings': {'a': 1}}, {'value': {'one': 1, 'two': 2}}])
def test_combined_setting_payload_rejected(extra):
    params = {'schema': 'org.gnome.desktop.interface', 'key': 'text-scaling-factor', 'value': 1.5, **extra}
    schema = build_tools('os', ['desktop.set_setting'], include_gui=False,
                         include_control_tools=False, strict_generic=True)[0]['function']['parameters']
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(params, schema)
    with pytest.raises(AdapterError):
        validate_action_params('desktop.set_setting', params)

class SettingsRunner:
    def __init__(self):
        self.state = {
            ('org.gnome.desktop.interface', 'text-scaling-factor'): '1.0',
            ('org.gnome.desktop.a11y.applications', 'screen-magnifier-enabled'): 'false',
            ('org.gnome.desktop.a11y.magnifier', 'mag-factor'): '2.0',
            ('org.gnome.desktop.session', 'idle-delay'): 'uint32 300',
            ('org.gnome.settings-daemon.plugins.power', 'idle-dim'): 'true',
        }
        self.writes = []
    def run(self, argv, **kwargs):
        assert argv[0] == 'gsettings'
        identity = tuple(argv[2:4])
        if argv[1] == 'set':
            self.state[identity] = argv[4]
            self.writes.append(identity)
            return {'stdout': '', 'stderr': '', 'returncode': 0}
        assert argv[1] == 'get'
        return {'stdout': self.state[identity], 'stderr': '', 'returncode': 0}

@pytest.mark.parametrize('schema,key,value', [
    ('org.gnome.desktop.interface', 'text-scaling-factor', 1.5),
    ('org.gnome.settings-daemon.plugins.power', 'idle-dim', False),
])
def test_text_size_and_dimming_change_no_other_setting(schema, key, value):
    runner = SettingsRunner()
    before = dict(runner.state)
    actions = OSActions(runner=runner)
    params = {'schema': schema, 'key': key, 'value': value}
    validate_action_params('desktop.set_setting', params)
    result = actions.dispatch('desktop.set_setting', params, 1)
    assert runner.writes == [(schema, key)]
    assert {k: v for k, v in runner.state.items() if k != (schema, key)} == {k: v for k, v in before.items() if k != (schema, key)}
    specs = _default_specs('desktop.set_setting', params, result)
    assert len(specs) == 1 and specs[0]['key'] == key
