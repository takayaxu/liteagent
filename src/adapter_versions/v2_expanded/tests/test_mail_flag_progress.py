from integrations.lite_agent.mail_flag_progress import model_progress
from integrations.lite_agent.state_model import RuntimeState, ExecutionEvent


def test_live_stage_tracks_actual_selection_and_toggle_and_excludes_other_tasks():
    state = RuntimeState(task_id='synthetic', domain='thunderbird',
        instruction='Add a star to every email in local invoices folder', events=[])
    assert model_progress(state)['stage'] == 'select_live_folder_messages'
    state.events.append(ExecutionEvent(step=1, timestamp_utc='', executed=True,
        proposed={'tool': 'gui_action', 'arguments': {'action': 'hotkey', 'keys': ['ctrl', 'a']}}))
    assert model_progress(state)['stage'] == 'star_selected_messages'
    state.events.append(ExecutionEvent(step=2, timestamp_utc='', executed=True,
        proposed={'tool': 'gui_action', 'arguments': {'action': 'press', 'key': 's'}}))
    assert model_progress(state)['stage'] == 'verify_live_stars'
    state.events[-1].error = {'failed': True}
    assert model_progress(state)['stage'] == 'star_selected_messages'
    state.domain = 'os'
    assert model_progress(state) is None
