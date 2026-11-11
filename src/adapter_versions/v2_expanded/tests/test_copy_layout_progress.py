from types import SimpleNamespace
from integrations.lite_agent.copy_layout_progress import model_progress
from integrations.lite_agent.state_model import ExecutionEvent


def test_layout_hint_retains_actual_replication_evidence_for_correction():
    event = ExecutionEvent(step=2, timestamp_utc='', executed=True, proposed={
        'kind': 'adapter', 'action': 'filesystem.copy_to_directories',
        'arguments': {'source': '/src/a/file.txt', 'destinations': ['/dst/a', '/dst/b']}})
    state = SimpleNamespace(instruction='Copy matching files preserving directory hierarchy',
                            domain='os', events=[event])
    hint = model_progress(state)
    assert hint['observed_operations'][0]['arguments']['destinations'] == ['/dst/a', '/dst/b']
    assert 'missing AND extra' in hint['next_step']
    assert 'unrelated' in hint['next_step']
    state.instruction = 'Copy this file to every destination directory'
    assert model_progress(state) is None


def test_real_messages_expose_layout_step_after_find():
    from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
    from integrations.lite_agent.state_model import RuntimeState
    state = RuntimeState(task_id='synthetic', domain='os',
        instruction='Copy files preserving directory hierarchy', events=[
        ExecutionEvent(step=1, timestamp_utc='', executed=True,
            proposed={'kind': 'adapter', 'action': 'filesystem.find',
                      'arguments': {'roots': ['/src'], 'name_patterns': ['*.txt']}})])
    agent = LiteAgent(LiteAgentConfig(base_url='http://unused', include_gui=False),
                      SimpleNamespace(), model_client=SimpleNamespace(client=object()))
    tools = [{'function': {'name': 'tools_search'}}]
    messages = agent._messages(state, b'png', tools=tools)
    assert 'Current copy-layout step' in messages[0]['content']
    assert 'observed_operations' in str(messages)
