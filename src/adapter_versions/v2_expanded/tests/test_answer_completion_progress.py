"""Observe answer-sheet blanks; never supply answer content or silently edit."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.answer_completion_progress import model_progress
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState

TARGET = 'Quiz 8:\nabc\n\nQuiz 9:\n\nQuiz 10:'


def state(events=()):
    return RuntimeState(task_id='synthetic', domain='multi_apps',
                        instruction='Complete the remaining answers in the document in the provided format.',
                        events=list(events))


def event(step, action, context=None, params=None, adapter='libreoffice_writer'):
    return ExecutionEvent(step=step, timestamp_utc='', executed=True,
        proposed={'kind': 'adapter', 'action': 'adapter.call', 'arguments': {
            'adapter': adapter, 'action': action, 'payload': {'params': params or {}}}},
        result={'context_hint': {'downstream_adapter': adapter, 'downstream_action': action,
                                'downstream_context': context or {}}})


def read(step, path='/tmp/Answers.docx', text=TARGET):
    return event(step, 'document.read_file', {'files': [{
        'path': path, 'text': text, 'status': 'ok', 'source_start_char': 0,
        'source_end_char': len(text), 'source_total_chars': len(text),
        'source_truncated': False, 'next_start_char': None}]}, {'path': path})


def found():
    return event(1, 'filesystem.find', {'matches': [{'path': path, 'kind': 'file'} for path in
        ['/tmp/Answers.docx', '/tmp/Quiz 9.docx', '/tmp/Quiz 10.docx']]}, adapter='os')


def tools(*routes):
    return [{'function': {'name': 'adapter__adapter_call', 'parameters': {'x-allowed-routes': [
        {'adapter': adapter, 'action': action} for adapter, action in routes]}}},
        {'function': {'name': 'tools_search'}}]


def ready():
    return state([found(), read(2), read(3, '/tmp/Quiz 9.docx', 'Quiz 9\n1. Question\na) First\nb) Second'),
                  read(4, '/tmp/Quiz 10.docx', 'Quiz 10\n1. Question\na) First\nb) Second')])


def test_locate_and_read_actual_target_not_search_hits_as_content():
    p = model_progress(state(), tools(('os', 'filesystem.find')))
    assert p['stage'] == 'locate_documents'
    assert p['suggested_tool_call']['arguments']['payload']['params']['roots'] == ['~']
    p = model_progress(state([found()]), tools(('libreoffice_writer', 'document.read_file')))
    assert p['stage'] == 'read_existing_answers'
    assert p['suggested_tool_call']['arguments']['payload']['params']['path'] == '/tmp/Answers.docx'


def test_source_reader_search_keeps_future_edit_capability_explicit():
    p = model_progress(state([found(), read(2)]), tools())
    assert p['stage'] == 'read_source_questions'
    assert p['suggested_tool_call']['arguments']['query'] == 'libreoffice_writer document.read_file text.find_replace'
    p = model_progress(state([found(), read(2)]), tools(('libreoffice_writer', 'document.read_file')))
    assert p['suggested_tool_call']['arguments']['payload']['params']['path'] == '/tmp/Quiz 9.docx'
    assert p['original_target']['sections'][0]['entry'] == 'abc'


def test_reader_does_not_activate_target_and_no_answer_payload_is_invented():
    s = ready()
    p = model_progress(s, tools(('os', 'desktop.open_path')))
    assert p['stage'] == 'activate_target'
    s.events.append(event(5, 'desktop.open_path', params={'path': '/tmp/Answers.docx'}, adapter='os'))
    p = model_progress(s, tools(('libreoffice_writer', 'text.find_replace')))
    assert p['stage'] == 'solve_and_fill_one_section'
    assert 'suggested_tool_call' not in p  # No invalid empty replacement call.
    assert p['write_contract']['observed_empty_heading_anchors'] == ['Quiz 9:', 'Quiz 10:']
    assert len(p['source_questions']) == 2


def test_unsaved_write_requires_save_and_readback_then_only_remaining_blank():
    s = ready()
    s.events += [event(5, 'desktop.open_path', params={'path': '/tmp/Answers.docx'}, adapter='os'),
                 event(6, 'text.find_replace')]
    assert model_progress(s, tools())['stage'] == 'save_current_edits'
    s.events.append(event(7, 'document.save'))
    assert model_progress(s, tools())['stage'] == 'read_saved_answers'
    s.events.append(read(8, text=TARGET.replace('Quiz 9:\n', 'Quiz 9:\nz\n')))
    p = model_progress(s, tools(('libreoffice_writer', 'text.find_replace')))
    assert p['stage'] == 'solve_and_fill_one_section'
    assert p['write_contract']['observed_empty_heading_anchors'] == ['Quiz 10:']
    assert p['original_target']['sections'][0]['entry'] == 'abc'


def test_existing_answers_are_protected_and_content_presence_not_correctness():
    s = ready()
    s.events.append(read(5, text=TARGET.replace('abc', 'changed')))
    assert model_progress(s, tools())['stage'] == 'restore_existing_answers'
    s = ready()
    s.events.append(read(5, text=TARGET.replace('Quiz 9:\n', 'Quiz 9:\nz\n').replace('Quiz 10:', 'Quiz 10:\nx')))
    p = model_progress(s, tools())
    assert p['stage'] == 'verify_completion'
    assert len(p['source_questions']) == 2
    assert 'presence is not correctness' in p['next_step']


@pytest.mark.parametrize('mode', [{}, {'protocol_recovery': True}, {'execution_recovery': True}])
def test_real_messages_keep_concrete_step_before_compacted_history(mode):
    s = state([found(), read(2)])
    available = tools(('libreoffice_writer', 'document.read_file'))
    before = deepcopy((s.events, available))
    agent = LiteAgent(LiteAgentConfig(base_url='http://unused/v1', include_gui=False),
                      SimpleNamespace(), model_client=SimpleNamespace(client=object()))
    text = agent._messages(s, b'png', tools=available, **mode)[-1]['content'][0]['text']
    assert text.startswith('Current step:')
    assert 'answer_completion_progress' in text
    assert '/tmp/Quiz 9.docx' in text
    assert (s.events, available) == before


def test_unrelated_tasks_do_not_trigger():
    s = state()
    s.instruction = 'Create a new spreadsheet.'
    assert model_progress(s, tools()) is None
