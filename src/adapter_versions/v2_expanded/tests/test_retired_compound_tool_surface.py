import pytest
from importlib import import_module
from integrations.lite_agent.state_model import RuntimeState
from integrations.lite_agent.tool_catalog import build_tools
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes

RETIRED=[('chrome','settings.set'),('gimp','image.adjust'),
         ('vs_code','debugging.configure'),('vs_code','editor.configure'),
         ('vs_code','files.configure'),('vs_code','settings.update'),
         ('vlc','preferences.configure'),('vlc','config.update'),
         ('os','desktop.set_accessibility_scale'),('os','desktop.set_dim_inactive'),
         ('os','archive.create_extract')]

@pytest.mark.parametrize('domain,action',RETIRED)
def test_stale_action_recommendations_cannot_recreate_public_tools(domain,action):
    assert build_tools(domain,[action],include_gui=False,include_control_tools=False,strict_generic=True)==[]
    module = import_module(("vscode" if domain == "vs_code" else domain) + "_adapter.schema")
    for invoke in (lambda: module.parse_action_request({"action": action, "params": {}}),
                   lambda: module.validate_action_params(action, {})):
        with pytest.raises(module.AdapterError) as error:
            invoke()
        assert error.value.details["replacement_actions"]
    tools=constrain_adapter_call_routes(build_tools('multi_apps',['adapter.call'],include_gui=False,strict_generic=True),[(domain,action)])
    assert all(t['function']['name']!='adapter__adapter_call' for t in tools)


def test_normal_control_and_public_actions_still_build():
    tools=build_tools('os',['tools_search','desktop.set_setting'],include_gui=False,strict_generic=True)
    names=[t['function']['name'] for t in tools]
    assert 'adapter__desktop_set_setting' in names
    assert 'tools_search' in names
    assert 'adapter__tools_search' not in names


def test_historical_recommendation_allows_completion_with_the_current_preference():
    state = RuntimeState(
        "synthetic", "vlc", "Allow multiple instances of VLC",
        recommended_actions=["preferences.configure"],
    )
    assert state.required_mutation_actions() == {"preferences.set_allow_multiple_instances"}
