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
from integrations.lite_agent.notes_preservation import argument_errors, requested, source_texts, model_progress
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


def source_read(step=0, text='Slide 1:\nSource text\nSlide 2:\nSecond note\nSlide 3:\nLast new note', path='/tmp/script.docx', **metadata):
    return event(step, 'document.read_file', {'path': path}, {
        'path': path, 'text': text, 'source_truncated': False, **metadata},
        domain='libreoffice_writer')


def write(step, index, text):
    return event(step, 'slide.set_notes', {'slide': index, 'text': text, 'source_reference': {
        'path': '/tmp/script.docx', 'heading': f'Slide {index + 1}:'}},
                 {'slide': index, 'text': text})


def errors(s, index, text, forwarded=True, reference=None):
    args = {'slide': index, 'text': text, 'source_reference': reference or {
        'path': '/tmp/script.docx', 'heading': f'Slide {index + 1}:'}}
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
    assert not errors(s, 0, 'Source text')
    assert not gate(s)['passed']  # Other initial pages remain unknown.


def test_completion_requires_every_missing_page_preservation_save_and_final_readback():
    initial = ['', 'Existing  notes! . ', ' \n']
    s = state(inspection(1, initial), write(2, 0, 'Source text'))
    assert not gate(s)['passed']  # One successful write used to pass this gate.
    s.events += [write(3, 2, 'Last new note'), inspection(4, ['Source text', initial[1], 'Last new note'])]
    assert not gate(s)['passed']  # Read-back without a save is insufficient.
    s.events.append(event(5, 'presentation.save'))
    assert not gate(s)['passed']  # Inspection must describe persisted state.
    s.events.append(inspection(6, ['Source text', initial[1], 'Last new note']))
    assert gate(s)['passed']


def test_changed_existing_notes_are_detected_and_exact_restoration_is_allowed():
    s = state(inspection(1, ['', 'Keep  spacing. .']), write(2, 0, 'Source text'),
              write(3, 1, 'Keep spacing.'), event(4, 'presentation.save'),
              inspection(5, ['Source text', 'Keep spacing.']))
    assert 'notes.existing_changed' in str(gate(s))
    assert not errors(s, 1, 'Keep  spacing. .')
    s.events += [write(6, 1, 'Keep  spacing. .'), event(7, 'presentation.save'),
                 inspection(8, ['Source text', 'Keep  spacing. .'])]
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
    assert not errors(s, 0, 'Source text')
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
    assert compact['slides_omitted_from_context'] > 0 or any(
        slide.get('text_shapes_omitted', 0) for slide in compact['slides'])
    assert [page['display_slide_number'] for page in compact['notes_status']] == [1, 2, 3, 4]
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
    assert not errors(s, 0, 'Source text')
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
    assert not errors(s, 0, 'Source text')


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
    assert source_texts(s)['/tmp/remarks.docx'] == 'abcdef'
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


def test_exact_page_reference_preserves_internal_newline_and_double_spaces():
    original = 'First  sentence.\nSecond sentence!'
    s = state(inspection(1, ['', '']))
    s.events[0] = source_read(text=f'Notes\nSlide 1:\n\t{original}\nSlide 2:\nOther page')
    assert not errors(s, 0, original)
    assert errors(s, 0, original.replace('\n', ' '))
    assert errors(s, 0, original.replace('  ', ' '))
    assert errors(s, 0, 'First  sentence.')  # Must not silently omit a sentence.
    assert errors(s, 1, original, reference={'path': '/tmp/script.docx', 'heading': 'Slide 1:'})
    assert errors(s, 1, original, reference={'path': '/tmp/script.docx', 'heading': 'Slide 2:'})
    assert errors(s, 0, original, reference={'path': '/tmp/unknown.docx', 'heading': 'Slide 1:'})
    assert errors(s, 0, original, reference={'path': '/tmp/script.docx', 'heading': 'Invented'})


def test_ambiguous_or_missing_source_page_labels_do_not_guess_correspondence():
    s = state(inspection(1, ['']))
    s.events[0] = source_read(text='Slide 1:\nOne\nSlide 1:\nAnother')
    assert errors(s, 0, 'One')
    s.events[0] = source_read(text='Unnumbered script\nOne')
    assert errors(s, 0, 'One')
    s.events[0] = source_read(text='Page 1:\nOne')
    assert not errors(s, 0, 'One', reference={'path': '/tmp/script.docx', 'heading': 'Page 1:'})


def test_completion_detects_wrong_page_text_and_missing_source_reference_after_save():
    s = state(inspection(1, ['', '']), write(2, 0, 'Source text'),
              write(3, 1, 'Source text'), event(4, 'presentation.save'),
              inspection(5, ['Source text', 'Source text']))
    assert 'notes.source_mismatch' in str(gate(s))
    s.events += [write(6, 1, 'Second note'), event(7, 'presentation.save'),
                 inspection(8, ['Source text', 'Second note'])]
    assert gate(s)['passed']
    # The write event is index 2 (source read, initial inspection, first write).
    s.events[2].proposed['arguments']['payload']['params'].pop('source_reference')
    assert 'notes.source_mismatch' in str(gate(s))


def test_public_source_reference_schema_native_validation_and_worker_preserve_text(monkeypatch):
    from jsonschema import validate
    from impress_adapter import uno_worker
    from impress_adapter.schema import validate_action_params
    from impress_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
    from impress_adapter.errors import AdapterError
    from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
    params = {'slide': 1, 'text': 'Exact  text.\nAnother line',
              'source_reference': {'path': '/tmp/script.docx', 'heading': 'Slide 2:'}}
    validate(params, STRICT_ACTION_PARAM_SCHEMAS['slide.set_notes'])
    validate_action_params('slide.set_notes', params)
    tools = constrain_adapter_call_routes(build_tools('multi_apps', ['adapter.call'], include_gui=False),
                                         [('libreoffice_impress', 'slide.set_notes')])
    assert 'source_reference' in str(tools)
    with pytest.raises(AdapterError):
        validate_action_params('slide.set_notes', {**params, 'source_reference': {'heading': 'Slide 2:'}})
    received = []
    monkeypatch.setattr(uno_worker, 'set_speaker_notes',
                        lambda page, text, **kw: received.append(text) or text)
    session = SimpleNamespace(page=lambda index: SimpleNamespace(getNotesPage=lambda: object()),
                              doc=SimpleNamespace(createInstance=lambda name: object()))
    result = uno_worker._set_notes(session, params)
    assert received == [params['text']]
    assert result['text'] == params['text']
    assert result['source_reference'] == params['source_reference']
    plain = {'slide': 0, 'text': 'Newly authored notes'}
    validate_action_params('slide.set_notes', plain)
    assert 'source_reference' not in uno_worker._set_notes(session, plain)


@pytest.mark.parametrize('original', ['You should also try to answer!\n', 'Keep dataset wording.\n'])
def test_protection_reason_survives_both_filters_without_embedding_document_text(original):
    from integrations.lite_agent.context_projection import sanitize
    from integrations.lite_agent.safety import sanitize_agent_visible_result
    s = state(inspection(1, ['', original]))
    error = {'type': 'ValueError', 'detail': errors(s, 1, 'Reworded')[0]}
    safe = sanitize(sanitize_agent_visible_result(error, s.task_id))
    assert 'already had notes' in safe['detail']
    assert 'Skip this page' in safe['detail']
    assert original not in safe['detail']
    # Existing protection against sensitive metadata in error prose is intact.
    assert sanitize({'error': {'detail': original}})['error']['detail'] == '<internal-benchmark-metadata>'


def test_progress_distinguishes_original_preservation_from_remaining_save_and_readback():
    initial = ['', 'You should also try to answer!\n']
    s = state(inspection(1, initial), write(2, 0, 'Source text'),
              inspection(3, ['Source text', initial[1]]))
    progress = model_progress(s)
    assert progress['pages'][1]['status'] == 'original retained; no write needed'
    assert progress['pages'][0]['status'] == 'filled and source checked'
    assert progress['save_required']
    s.events.append(event(4, 'presentation.save'))
    progress = model_progress(s)
    assert not progress['save_required']
    assert all(page['final_readback_required'] for page in progress['pages'])
    s.events.append(inspection(5, ['Source text', initial[1]]))
    assert not any(page['final_readback_required'] for page in model_progress(s)['pages'])
    assert gate(s)['passed']
    agent = LiteAgent(LiteAgentConfig(base_url='http://unused/v1', include_gui=False),
                      SimpleNamespace(), model_client=SimpleNamespace(client=object()))
    messages = json.dumps(agent._messages(s, b'png'), ensure_ascii=False)
    assert 'notes_progress' in messages
    assert 'original retained; no write needed' in messages
    s.instruction = 'Write new notes for the presentation.'
    assert model_progress(s) is None


@pytest.mark.parametrize('body_edit', [
    'Also remove the trailing empty paragraph from the body text box on slide 2. Keep all slides and preserve existing notes.',
    'Delete the picture on slide 3; keep all speaker notes.',
    'Replace the title with the new title.',
    'Replace the title with text from the speaker notes document.',
    'Remove the empty paragraph, then fill the missing speaker notes.',
    'Correct the body text and preserve existing notes.',
    "Do not overwrite completed notes. Remove the empty body paragraph.",
])
def test_independent_body_edit_does_not_disable_notes_contract(body_edit):
    s = state(inspection(1, ['', 'Keep  this. .']))
    s.instruction += ' ' + body_edit
    assert requested(s)
    assert errors(s, 1, 'Keep this.')
    assert errors(s, 0, 'Source text plus unrelated passage')
    assert model_progress(s)['pages'][1]['status'] == 'original retained; no write needed'
    s.events = [e for e in s.events if e.proposed['arguments'].get('action') != 'document.read_file']
    assert 'No complete source-text read' in str(errors(s, 0, 'Guessed'))


@pytest.mark.parametrize('note_edit', [
    'Also remove existing speaker notes from slide 2.',
    'Delete the empty paragraphs from speaker notes.',
    'Replace the title and speaker notes with revised content.',
    'Rewrite the body text and replace existing notes.',
    'Correct typos in the notes.',
    'Revise them.',  # Ambiguous objects must not block a possibly requested edit.
])
def test_explicit_or_ambiguous_notes_edit_remains_legal(note_edit):
    s = state(inspection(1, ['Original']))
    s.instruction += ' ' + note_edit
    assert not requested(s)
    assert not errors(s, 0, 'Revised')
