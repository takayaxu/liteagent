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
