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
