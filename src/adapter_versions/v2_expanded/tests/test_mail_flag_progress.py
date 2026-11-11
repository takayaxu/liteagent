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
    assert model_progress(state)['stage'] == 'read_back_live_stars'
    state.events[-1].error = {'failed': True}
    assert model_progress(state)['stage'] == 'star_selected_messages'
    state.domain = 'os'
    assert model_progress(state) is None


def test_full_native_readback_is_required_for_gui_completion():
    from integrations.lite_agent.mail_flag_progress import verified_live_mutation
    from integrations.lite_agent.completion_policy import collect_initial_completion_evidence
    toggle = ExecutionEvent(step=1, timestamp_utc='', executed=True,
        proposed={'kind': 'gui', 'tool': 'gui_action',
                  'arguments': {'action': 'press', 'key': 's'}})
    body = {'folder': 'Local Folders/invoices', 'matched_count': 2, 'returned_count': 2,
            'messages': [{'starred': True}, {'starred': True}]}
    query = ExecutionEvent(step=2, timestamp_utc='', executed=True,
        proposed={'kind': 'adapter', 'action': 'messages.query',
                  'arguments': {'folder_name': 'invoices'}},
        result={'context_hint': {'downstream_context': body}})
    state = RuntimeState(task_id='synthetic', domain='thunderbird',
        instruction='Add a star to every email in local invoices folder', events=[toggle, query])
    assert verified_live_mutation(state) is toggle
    successful, mutations, missing, _ = collect_initial_completion_evidence(
        state, None, is_read_only_action=lambda a: a=='messages.query',
        is_save_action=lambda a: False, relevance_score=lambda *args: 2)
    assert mutations == [toggle]
    assert not missing
    for field, value in [('matched_count', 3), ('folder', 'Other'), ('returned_count', 1)]:
        old = body[field]
        body[field] = value
        assert verified_live_mutation(state) is None
        body[field] = old
    body['messages'][1]['starred'] = False
    assert verified_live_mutation(state) is None
    body['messages'][1]['starred'] = True
    toggle.error = {'failed': True}
    assert verified_live_mutation(state) is None
