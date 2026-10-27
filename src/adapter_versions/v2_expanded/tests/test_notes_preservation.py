"""Protect user-completed notes and require complete persisted read-back."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.adapter_results import (
    compact_context_hint_for_model, compact_presentation_hint_for_model,
)
from integrations.lite_agent.completion import CompletionMixin
from integrations.lite_agent.notes_preservation import argument_errors, requested
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.tool_catalog import build_tools


INSTRUCTION = (
    'My PowerPoint and speaking notes document are on the desktop. '
    'Complete the remaining notes; some slides are already completed.'
)


def event(step, action, args=None, payload=None, domain='libreoffice_impress'):
    body = {'status': 'ok', 'result': payload or {},
            'verification': {'passed': True, 'checks': []}}
    return ExecutionEvent(
        step=step, timestamp_utc='2030-01-01T00:00:00Z', executed=True, validated=True,
        proposed={'kind': 'adapter', 'action': 'adapter.call', 'arguments': {
            'adapter': domain, 'action': action, 'payload': {'params': args or {}}}},
        result={'adapter_response': {'result': {'adapter': domain, 'action': action,
                                               'response': body}}},
    )


def inspection(step, notes, indices=None, url='file:///tmp/Talk.pptx', count=None):
    indices = list(range(len(notes))) if indices is None else indices
    return event(step, 'presentation.inspect', payload={
        'identity': {'url': url}, 'slide_count': len(notes) if count is None else count,
        'slides': [{'slide': i, 'notes': n} for i, n in zip(indices, notes)],
    })


def state(*events):
    return RuntimeState(task_id='synthetic-notes', domain='multi_apps',
                        instruction=INSTRUCTION, events=[source_read(), *events])


def source_read(step=0, text='Observed source script', path='/tmp/script.docx', **metadata):
    return event(step, 'document.read_file', {'path': path}, {
        'path': path, 'text': text, 'source_truncated': False, **metadata},
        domain='libreoffice_writer')


def write(step, index, text):
    return event(step, 'slide.set_notes', {'slide': index, 'text': text},
                 {'slide': index, 'text': text})


def errors(s, index, text, forwarded=True):
    args = {'slide': index, 'text': text}
    if forwarded:
        return argument_errors(s, 'adapter.call', {
            'adapter': 'libreoffice_impress', 'action': 'slide.set_notes',
            'payload': {'params': args}})
    s = deepcopy(s)
    s.domain = 'libreoffice_impress'
    return argument_errors(s, 'slide.set_notes', args)


def gate(s):
    return CompletionMixin._generic_completion_gate(s)


@pytest.mark.parametrize('forwarded', [False, True])
def test_existing_spaces_and_punctuation_are_protected_without_rewriting(forwarded):
    original = 'Keep  my notes. . \n'
    s = state(inspection(1, ['', original]))
    assert not errors(s, 0, 'Source text', forwarded)
    assert errors(s, 1, 'Keep my notes.', forwarded)
    assert not errors(s, 1, original, forwarded)
    assert s.events[1].result == state(inspection(1, ['', original])).events[1].result


def test_unknown_or_stale_target_is_not_treated_as_blank():
    s = state(inspection(1, [''], [0], count=3))
    assert errors(s, 2, 'Guessed text')
    s.events.append(write(2, 0, 'Observed source'))
    assert errors(s, 0, 'Another version')
    s.events.append(inspection(3, ['Observed source'], [0], count=3))
    assert not errors(s, 0, 'A deliberate correction')
    assert not gate(s)['passed']  # Other initial pages remain unknown.


def test_completion_requires_every_missing_page_preservation_save_and_final_readback():
    initial = ['', 'Existing  notes! . ', ' \n']
    s = state(inspection(1, initial), write(2, 0, 'First new note'))
    assert not gate(s)['passed']  # One successful write used to pass this gate.
    s.events += [write(3, 2, 'Last new note'), inspection(4, ['First new note', initial[1], 'Last new note'])]
    assert not gate(s)['passed']  # Read-back without a save is insufficient.
    s.events.append(event(5, 'presentation.save'))
    assert not gate(s)['passed']  # Inspection must describe persisted state.
    s.events.append(inspection(6, ['First new note', initial[1], 'Last new note']))
    assert gate(s)['passed']


def test_changed_existing_notes_are_detected_and_exact_restoration_is_allowed():
    s = state(inspection(1, ['', 'Keep  spacing. .']), write(2, 0, 'New note'),
              write(3, 1, 'Keep spacing.'), event(4, 'presentation.save'),
              inspection(5, ['New note', 'Keep spacing.']))
    assert 'notes.existing_changed' in str(gate(s))
    assert not errors(s, 1, 'Keep  spacing. .')
    s.events += [write(6, 1, 'Keep  spacing. .'), event(7, 'presentation.save'),
                 inspection(8, ['New note', 'Keep  spacing. .'])]
    assert gate(s)['passed']


def test_explicit_replacement_keeps_public_set_notes_legal():
    s = state(inspection(1, ['Original']))
    s.instruction = 'Replace all PowerPoint speaker notes with the revised desktop document.'
    assert not requested(s)
    assert not errors(s, 0, 'Revised')
    s.instruction = INSTRUCTION + " Don't overwrite completed notes."
    assert requested(s)
    assert errors(s, 0, 'Revised')


def test_document_switch_and_gui_do_not_reuse_stale_target_observations():
    s = state(inspection(1, ['Keep!']),
              inspection(2, [''], url='file:///tmp/Other.pptx'))
    assert not errors(s, 0, 'New')
    s.events.append(inspection(3, ['Keep!']))
    assert errors(s, 0, 'New')
    s.events.append(ExecutionEvent(step=4, timestamp_utc='2030-01-01T00:00:00Z',
                                  proposed={'kind': 'gui'}, validated=True, executed=True))
    assert errors(s, 0, 'New')
    s.events.append(inspection(5, ['Keep!']))
    assert errors(s, 0, 'New')


def test_notes_inventory_survives_shape_compaction_in_actual_messages():
    notes = ['', 'Keep this.', ' \n', 'Preserve  punctuation. .']
    native = {'identity': {'url': 'file:///tmp/Talk.pptx'}, 'slide_count': len(notes),
              'slides': [{'slide': i, 'notes': text, 'text_shapes': [
                  {'index': 0, 'path': [0], 'lines': ['Large body'] * 100,
                   'paragraphs': [{'text': 'Large body'}] * 100}]} for i, text in enumerate(notes)]}
    hint = compact_presentation_hint_for_model(native)
    compact = compact_context_hint_for_model(hint, remaining_chars=6000)
    assert [p['has_speaker_notes'] for p in compact['notes_status']] == [False, True, False, True]
    assert compact['slides_omitted_from_context'] > 0
    s = state()
    s.events = [ExecutionEvent(step=1, timestamp_utc='2030-01-01T00:00:00Z', executed=True,
                              proposed={'kind': 'adapter', 'action': 'presentation.inspect', 'arguments': {}},
                              result={'context_hint': hint})]
    agent = LiteAgent(LiteAgentConfig(base_url='http://unused/v1', include_gui=False),
                      SimpleNamespace(), model_client=SimpleNamespace(client=object()))
    messages = json.dumps(agent._messages(s, b'png'), ensure_ascii=False)
    assert 'notes_status' in messages
    assert 'notes_length' in messages
    assert 'preserve existing notes exactly' in messages


def test_truncated_envelope_uses_exact_retained_notes_but_not_truncated_note_text():
    original = 'Retain  this! . '
    initial = inspection(1, ['', original])
    payload = initial.result['adapter_response']['result']['response']['result']
    initial.result = {'adapter_response': {'truncated': True, 'preview': 'not JSON'},
                      'context_hint': {'downstream_context': payload}}
    s = state(initial)
    assert not errors(s, 0, 'Fill this blank')
    assert errors(s, 1, 'Reworded')
    payload['slides'][0]['notes'] = '...<truncated>...'
    assert errors(s, 0, 'Cannot guess original')


def test_protected_write_is_rejected_before_the_executor_receives_it():
    s = state(inspection(1, ['', 'Keep  exact. .']))
    s.domain = 'libreoffice_impress'
    class NoExecution:
        def execute(self, *args, **kwargs):
            raise AssertionError('Protected note must never reach the Adapter')
    agent = LiteAgent(LiteAgentConfig(base_url='http://unused/v1', include_gui=False),
                      NoExecution(), model_client=SimpleNamespace(client=object()))
    result = agent.execute_proposal(s, {
        'tool': 'adapter__slide_set_notes', 'arguments_raw': json.dumps({
            'slide': 1, 'text': 'Keep exact.'}),
        '_model_visible_tools': build_tools(s.domain, ['slide.set_notes'], include_gui=False)})
    assert result.executed is False
    assert 'already had notes' in str(result.error)


def test_multi_apps_application_settings_do_not_require_presentation_save():
    e = event(1, 'settings.set', {'name': 'test', 'value': True})
    s = state(e)
    s.instruction = 'Change the Impress application preference.'
    missing = str(gate(s).get('missing', []))
    assert 'save the LibreOffice document' not in missing
    assert 'perform structural read-back' not in missing


def test_transfer_needs_actual_source_text_not_destination_or_listing():
    s = state(inspection(1, ['', 'Keep existing']))
    s.events = s.events[1:]
    assert 'No complete source-text read' in str(errors(s, 0, 'Invented script'))
    assert not errors(s, 1, 'Keep existing')  # Restoration needs no source file.
    assert 'notes.source_unread' in str(gate(s))
    s.events.append(event(2, 'filesystem.find', payload={
        'matches': [{'path': '/tmp/script.docx'}]}, domain='os'))
    assert errors(s, 0, 'Invented script')
    s.events.append(source_read(3))
    assert not errors(s, 0, 'Model-selected source excerpt')


def test_named_source_and_complete_window_coverage_are_required():
    s = state(inspection(1, ['']))
    s.events = s.events[1:]
    s.instruction = INSTRUCTION + ' Use remarks.docx.'
    s.events.append(source_read(2, path='/tmp/unrelated.docx'))
    assert errors(s, 0, 'Unread script')
    s.events.append(source_read(3, 'abc', path='/tmp/remarks.docx',
                   source_start_char=0, source_end_char=3, source_total_chars=6,
                   source_truncated=True, next_start_char=3))
    assert errors(s, 0, 'Partial script')
    s.events.append(source_read(4, 'ef', path='/tmp/remarks.docx',
                   source_start_char=4, source_end_char=6, source_total_chars=6))
    assert errors(s, 0, 'Gap in read coverage')
    s.events.append(source_read(5, 'd', path='/tmp/remarks.docx',
                   source_start_char=3, source_end_char=4, source_total_chars=6))
    assert not errors(s, 0, 'abc')
    s.events.append(event(6, 'file.write_text', {'path': '/tmp/remarks.docx'}, domain='vs_code'))
    assert errors(s, 0, 'Stale source')


def test_failed_or_projected_truncated_source_read_is_not_proof():
    s = state(inspection(1, ['']))
    s.events = s.events[1:]
    failed = source_read(2)
    failed.error = {'status': 'failed'}
    s.events += [failed, source_read(3, '...<truncated>...'),
                 source_read(4, 'Only a preview', context_truncated=True)]
    assert errors(s, 0, 'Unproven source')
    s.instruction = 'Write new speaker notes for all PowerPoint slides.'
    assert not errors(s, 0, 'Newly authored text is explicitly requested')
