from types import SimpleNamespace

import pytest

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.task_stage_prompts import stage_prompt_text
from integrations.lite_agent.tool_catalog import build_tools


@pytest.mark.parametrize('recovery', [{}, {'protocol_recovery': True}, {'execution_recovery': True}])
def test_prompt_is_isolated_by_exact_task_and_tool_in_actual_messages(recovery):
    marker = 'SCOPED_STAGE_MARKER: inspect the current visible state.'
    overrides = {'target-task': [{'when_tool': 'gui_action', 'text': marker}]}
    def agent(prompts):
        return LiteAgent(LiteAgentConfig(base_url='http://unused', task_stage_prompts=prompts),
                         SimpleNamespace(), model_client=SimpleNamespace(client=None))
    baseline, candidate = agent(None), agent(overrides)
    for task_id in ['target-task', 'different-task']:
        state = RuntimeState(task_id=task_id, domain='os', instruction='Open the application.')
        for gui in [False, True]:
            tools = build_tools('os', [], include_gui=gui)
            expected = baseline._messages(state, b'synthetic', tools=tools, **recovery)
            actual = candidate._messages(state, b'synthetic', tools=tools, **recovery)
            if task_id == 'target-task' and gui:
                assert marker in actual[0]['content']
                assert actual[1:] == expected[1:]
            else:
                assert actual == expected


def test_stage_follows_only_successful_actions_and_stops_after_success():
    prompts = {'target': [{'after_action': 'filesystem.find', 'until_action': 'desktop.open_path',
                           'text': 'Use the observed file path.'}]}
    state = RuntimeState(task_id='target', domain='os', instruction='Open the file.')
    def add(action, executed):
        state.events.append(ExecutionEvent(step=len(state.events)+1, timestamp_utc='test',
            proposed={'kind': 'adapter', 'action': action, 'arguments': {}}, executed=executed))
    assert stage_prompt_text(prompts, state, []) == ''
    add('filesystem.find', False)
    assert stage_prompt_text(prompts, state, []) == ''
    add('filesystem.find', True)
    assert stage_prompt_text(prompts, state, []) == 'Use the observed file path.'
    add('desktop.open_path', True)
    assert stage_prompt_text(prompts, state, []) == ''


@pytest.mark.parametrize('invalid', [[], {'target': 'text'}, {'target': [{}]},
    {'target': [{'text': 'hint', 'match_instruction': 'keyword'}]},
    {'target': [{'text': 'hint', 'when_tool': []}]}])
def test_invalid_stage_configuration_is_rejected(invalid):
    with pytest.raises(ValueError):
        LiteAgentConfig(base_url='http://unused', task_stage_prompts=invalid)


def test_bound_context_requires_exact_task_and_single_empty_input_tool():
    from integrations.lite_agent.task_stage_prompts import bound_call_context
    stages = {'target': [{'when_tool': 'bound', 'text': 'Serialize the current call.',
                          'context_mode': 'bound_call'}]}
    tool = {'type': 'function', 'function': {'name': 'bound', 'parameters': {
        'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}}}
    state = RuntimeState(task_id='target', domain='os', instruction='Edit the file.')
    assert 'Emit one tool call with {}' in bound_call_context(stages, state, [tool])
    assert bound_call_context(stages, state, [tool, tool]) is None
    tool['function']['parameters']['properties'] = {'path': {'type': 'string'}}
    assert bound_call_context(stages, state, [tool]) is None
    state.task_id = 'different'
    assert bound_call_context(stages, state, [tool]) is None


def test_stage_recognizes_owner_qualified_actions_through_multi_apps_wrapper():
    stages = {'target': [{'after_action': 'thunderbird:contacts.export_csv',
                          'until_action': 'os:desktop.open_path', 'text': 'Open the observed CSV.'}]}
    state = RuntimeState(task_id='target', domain='multi_apps', instruction='Convert the exported data.')
    def add(owner, action):
        state.events.append(ExecutionEvent(step=len(state.events)+1, timestamp_utc='test',
            proposed={'kind': 'adapter', 'action': 'adapter.call', 'arguments': {
                'adapter': owner, 'action': action, 'payload': {'params': {}}}}, executed=True))
    assert stage_prompt_text(stages, state, []) == ''
    add('thunderbird', 'contacts.export_csv')
    assert stage_prompt_text(stages, state, []) == 'Open the observed CSV.'
    add('os', 'desktop.open_path')
    assert stage_prompt_text(stages, state, []) == ''
