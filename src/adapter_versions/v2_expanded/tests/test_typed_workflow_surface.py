from copy import deepcopy
from types import SimpleNamespace
import json

from jsonschema import Draft202012Validator

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.atomic_tool_surface import atomic_provider_surface, restore_adapter_arguments
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes, typed_adapter_route_surface
from integrations.lite_agent.state_model import RuntimeState
from integrations.lite_agent.tool_catalog import build_tools


ROUTES = [('libreoffice_impress', name) for name in (
    'presentation.export', 'presentation.inspect', 'shape.export_image',
    'shape.format_text', 'slide.format_text_roles', 'slides.format_text_roles',
)]


def public_tools(routes=ROUTES):
    return constrain_adapter_call_routes(
        build_tools('multi_apps', ['adapter.call'], include_gui=False, strict_generic=True), routes,
    )


def test_complete_observed_route_set_is_typed_without_losing_count_constraints():
    original = public_tools()
    before = deepcopy(original)
    typed = typed_adapter_route_surface(original)
    provider, bindings = atomic_provider_surface(typed)
    assert {(value['adapter'], value['action']) for value in bindings.values()} == set(ROUTES)
    assert len(bindings) == 6
    exported = next(value for value in bindings.values() if value['action'] == 'presentation.export')
    assert exported['schema']['properties']['format']['enum'] == ['pptx', 'odp', 'pdf', 'png', 'jpg']
    assert list(Draft202012Validator(exported['schema']).iter_errors({'format': 'docx', 'url': '/output.docx'}))
    assert not list(Draft202012Validator(exported['schema']).iter_errors({'format': 'pdf', 'url': '/output.pdf'}))
    boxed = next(value for value in bindings.values() if value['action'] == 'slide.format_text_roles')
    assert boxed['payload_boxed'] is True
    invalid = {'params': {'slide': 0, 'roles': ['all']}, 'document': {'url': '/source.pptx'}}
    assert list(Draft202012Validator(boxed['schema']).iter_errors(invalid))
    valid = {'params': {'slide': 0, 'roles': ['all'], 'font_size': 12}, 'document': {'url': '/source.pptx'}}
    assert not list(Draft202012Validator(boxed['schema']).iter_errors(valid))
    restored = restore_adapter_arguments(valid, boxed)
    assert restored['payload'] == valid
    wrapper = next(t['function']['parameters'] for t in typed if t['function']['name'] == 'adapter__adapter_call')
    assert not list(Draft202012Validator(wrapper).iter_errors(restored))
    assert original == before
    # The boxed representation is explicitly opt-in at the route union.
    unmarked = deepcopy(typed)
    next(t for t in unmarked if t['function']['name'] == 'adapter__adapter_call')['function']['parameters'].pop('x-typed-route-surface')
    assert not atomic_provider_surface(unmarked)[1]


def test_incomplete_or_live_constrained_surface_is_left_untouched():
    incomplete = public_tools([('chrome', 'page.read'), ('chrome', 'browser.inspect')])
    assert typed_adapter_route_surface(incomplete) is incomplete
    constrained = public_tools()
    payload = next(t['function']['parameters'] for t in constrained if t['function']['name'] == 'adapter__adapter_call')['properties']['payload']
    payload['properties']['params']['properties'] = {'url': {'enum': ['/only/observed.pdf']}}
    assert typed_adapter_route_surface(constrained) is constrained


def test_agent_opts_in_only_for_selected_exact_task_stage():
    target_id = 'c72b3a05-2d3c-4e6f-8a12-95df7e01b634'
    prompts = {target_id: [{'context_mode': 'typed_workflow_call', 'text': 'Use native contracts.'}]}
    captured = []
    def propose(**kwargs):
        captured.append(kwargs['tools'])
        return {'tool': 'tools_search', 'arguments_raw': json.dumps({'query': 'native inspect'})}
    agent = LiteAgent(LiteAgentConfig(base_url='http://unused', task_stage_prompts=prompts),
                      SimpleNamespace(), model_client=SimpleNamespace(client=None, propose=propose))
    original = public_tools()
    agent.tools = lambda state: deepcopy(original)
    agent.propose(RuntimeState(task_id='d15ae708-54b4-4ec5-a285-4d92e43f19a7', domain='multi_apps', instruction='Read source text.'), b'synthetic')
    assert captured[-1] == original
    agent.propose(RuntimeState(task_id=target_id, domain='multi_apps', instruction='Read source text.'), b'synthetic')
    assert captured[-1] == typed_adapter_route_surface(original)
