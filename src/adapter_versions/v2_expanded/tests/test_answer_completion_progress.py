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
    assert p['stage'] == 'discover_required_operation'
    assert p['suggested_tool_call']['arguments']['query'] == 'libreoffice_writer document.read_file paragraph.replace_text document.inspect'
    p = model_progress(state([found(), read(2)]), tools(('libreoffice_writer', 'document.read_file')))
    assert p['suggested_tool_call']['arguments']['payload']['params']['path'] == '/tmp/Quiz 9.docx'
    assert p['original_target']['sections'][0]['entry'] == 'abc'


def test_reader_does_not_activate_target_and_no_answer_payload_is_invented():
    s = ready()
    p = model_progress(s, tools(('os', 'desktop.open_path')))
    assert p['stage'] == 'activate_target'
    s.events.append(event(5, 'desktop.open_path', params={'path': '/tmp/Answers.docx'}, adapter='os'))
    assert model_progress(s, tools(('libreoffice_writer', 'document.inspect')))['stage'] == 'inspect_live_answer_paragraphs'
    s.events.append(event(6, 'document.inspect', {'paragraph_details': [
        {'index': 3, 'text': 'Quiz 9:', 'text_length': 7}, {'index': 4, 'text': '', 'text_length': 0}]}))
    p = model_progress(s, tools(('libreoffice_writer', 'paragraph.replace_text')))
    assert p['stage'] == 'solve_and_fill_one_section'
    assert 'suggested_tool_call' not in p  # No invalid empty replacement call.
    assert p['write_contract']['observed_empty_heading_anchors'] == ['Quiz 9:']
    assert p['current_source_paths'] == ['/tmp/Quiz 9.docx']


def test_unsaved_write_requires_save_and_readback_then_only_remaining_blank():
    s = ready()
    s.events += [event(5, 'desktop.open_path', params={'path': '/tmp/Answers.docx'}, adapter='os'),
                 event(6, 'text.find_replace')]
    assert model_progress(s, tools(('libreoffice_writer', 'document.save')))['stage'] == 'save_current_edits'
    s.events.append(event(7, 'document.save'))
    assert model_progress(s, tools(('libreoffice_writer', 'document.read_file')))['stage'] == 'read_saved_answers'
    s.events.append(read(8, text=TARGET.replace('Quiz 9:\n', 'Quiz 9:\nz\n')))
    s.events.append(event(9, 'document.inspect', {'paragraph_details': [
        {'index': 5, 'text': 'Quiz 10:', 'text_length': 8}]}))
    p = model_progress(s, tools(('libreoffice_writer', 'paragraph.replace_text')))
    assert p['stage'] == 'solve_and_fill_one_section'
    assert p['write_contract']['observed_empty_heading_anchors'] == ['Quiz 10:']
    assert p['original_target']['sections'][0]['entry'] == 'abc'


def test_existing_answers_are_protected_and_content_presence_not_correctness():
    s = ready()
    s.events.append(read(5, text=TARGET.replace('abc', 'changed')))
    assert model_progress(s, tools(('libreoffice_writer', 'text.find_replace')))['stage'] == 'restore_existing_answers'
    s = ready()
    s.events.append(read(5, text=TARGET.replace('Quiz 9:\n', 'Quiz 9:\nz\n').replace('Quiz 10:', 'Quiz 10:\nx')))
    p = model_progress(s, tools())
    assert p['stage'] == 'verify_completion'
    assert len(p['source_questions']) == 2
    assert 'correct length is not a correct answer' in p['next_step']


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


def test_duplicate_answers_trigger_shape_repair_at_observed_paragraphs():
    s = ready()
    s.events += [event(5, 'desktop.open_path', params={'path': '/tmp/Answers.docx'}, adapter='os'),
                 read(6, text=TARGET.replace('Quiz 9:\n', 'Quiz 9:\na\nb\n')),
                 event(7, 'document.inspect', {'paragraph_details': [
                     {'index': 4, 'text': 'a', 'text_length': 1},
                     {'index': 5, 'text': 'b', 'text_length': 1}]})]
    p = model_progress(s, tools(('libreoffice_writer', 'paragraph.replace_text')))
    assert p['stage'] == 'repair_answer_shape'
    assert p['answer_shape_issues'][0]['required_letter_count'] == 1
    assert p['answer_shape_issues'][0]['observed_entry'] == 'a\nb'
    assert p['live_paragraphs'][0]['index'] == 4
    assert 'suggested_tool_call' not in p


def test_numbered_questions_and_system_step_contain_no_runtime_selected_answers():
    s = ready()
    s.events += [event(5, 'desktop.open_path', params={'path': '/tmp/Answers.docx'}, adapter='os'),
                 event(6, 'document.inspect', {'paragraph_details': [
                     {'index': 3, 'text': 'Quiz 9:', 'text_length': 7}]})]
    available = tools(('libreoffice_writer', 'paragraph.replace_text'))
    p = model_progress(s, available)
    assert p['current_section'] == 'Quiz 9:'
    assert p['current_questions'][0]['options'] == {'a': 'First', 'b': 'Second'}
    assert p['answer_position_checklist'] == [{'output_position': 1, 'source_question': 1}]
    assert 'selected_answer' not in str(p['current_questions'])
    agent = LiteAgent(LiteAgentConfig(base_url='http://unused/v1', include_gui=False),
                      SimpleNamespace(), model_client=SimpleNamespace(client=object()))
    messages = agent._messages(s, b'png', tools=available)
    assert 'takes precedence over general phase hints' in messages[0]['content']
    assert 'original answer example gives FORMAT ONLY' in messages[0]['content']


def test_discovery_turn_omits_questions_and_stale_target_but_keeps_exact_next_call():
    s = ready()
    s.events += [event(5, 'desktop.open_path', params={'path': '/tmp/Answers.docx'}, adapter='os'),
                 event(6, 'paragraph.replace_text'), event(7, 'document.save')]
    available = tools()
    p = model_progress(s, available)
    assert p['stage'] == 'discover_required_operation'
    assert p['required_operation'] == 'libreoffice_writer.document.read_file'
    assert 'source_questions' not in p and 'current_questions' not in p
    assert 'sections' not in p['target']
    assert p['target']['reflects_latest_edit_and_save'] is False
    assert 'text' not in p['original_target']
    agent = LiteAgent(LiteAgentConfig(base_url='http://unused/v1', include_gui=False),
                      SimpleNamespace(), model_client=SimpleNamespace(client=object()))
    text = agent._messages(s, b'png', tools=available)[-1]['content'][0]['text']
    assert len(text) < 10000
    assert 'ONLY tool discovery' in text
    assert 'Question' not in text


def test_write_contract_binds_exact_observed_empty_paragraph_without_answers():
    s = ready()
    s.events += [event(5, 'desktop.open_path', params={'path': '/tmp/Answers.docx'}, adapter='os'),
                 event(6, 'document.inspect', {'paragraph_details': [
                     {'index': 3, 'text': 'Quiz 9:', 'text_length': 7},
                     {'index': 4, 'text': '', 'text_length': 0}]})]
    p = model_progress(s, tools(('libreoffice_writer', 'paragraph.replace_text')))
    assert p['write_contract']['index'] == 4
    assert p['write_contract']['observed_destination_text'] == ''
    assert p['current_source_paths'] == ['/tmp/Quiz 9.docx']
    assert 'source_questions' not in p
    assert 'paragraphs' not in p['write_contract']
