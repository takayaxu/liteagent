from copy import deepcopy
from types import SimpleNamespace

import pytest

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.grading_progress import model_progress
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


def event(step, adapter, action, body=None, params=None):
    return ExecutionEvent(step=step, timestamp_utc='', executed=True,
        proposed={'kind': 'adapter', 'action': 'adapter.call', 'arguments': {'adapter': adapter, 'action': action,
            'payload': {'params': params or {}}}},
        result={'context_hint': {'downstream_context': body or {}}})


def state(events=()):
    return RuntimeState(task_id='synthetic', domain='multi_apps',
        instruction="Grade the remaining students answers against the answer key and record detailed scoring in the spreadsheet.",
        events=list(events))


def tools(*routes):
    return [{'function': {'name': 'adapter__adapter_call', 'parameters': {
        'x-allowed-routes': [{'adapter': a, 'action': b} for a, b in routes]}}},
        {'function': {'name': 'tools_search'}}]


def table(blank=True):
    return {'name': 'Scores', 'returned_range': 'A1:E3',
        'display_text': [['Student ID', 'Name', 'Q1', 'Q2', 'Total'],
                         ['17', 'Ada', '1', '0', '5'],
                         ['18', 'Bea', '', '', ''] if blank else ['18', 'Bea', '0', '1', '5']],
        'cell_addresses': [['A1','B1','C1','D1','E1'], ['A2','B2','C2','D2','E2'],
                           ['A3','B3','C3','D3','E3']]}


def read(step, path, text):
    return event(step, 'libreoffice_writer', 'document.read_file', {'files': [{
        'path': path, 'text': text, 'status': 'ok', 'source_start_char': 0,
        'source_end_char': len(text), 'source_total_chars': len(text), 'source_truncated': False}]})


def ready():
    return state([event(1, 'libreoffice_calc', 'workbook.inspect',
        {'url':'file:///tmp/exams/marks.xlsx','active_sheet':'Scores'}),
        event(2, 'libreoffice_calc', 'workbook.read_file', {'sheets':[table()]}),
        event(3, 'os', 'filesystem.find', {'matches': [
            {'path':'/tmp/exams/Reference.docx','kind':'file'},
            {'path':'/tmp/exams/student.docx','kind':'file'}], 'truncated':False}, {'name_patterns':['*']}),
        read(4, '/tmp/exams/Reference.docx', 'Reference answers: 5 points each. Q1 A; Q2 B'),
        read(5, '/tmp/exams/student.docx', 'Student ID: 18 Bea. Q1 C; Q2 B')])


def test_real_inventory_broadens_case_sensitive_globs_and_keeps_source_immutable():
    s=ready()
    s.events=s.events[:2]
    p=model_progress(s, tools(('os','filesystem.find')))
    assert p['suggested_tool_call']['arguments']['payload']['params']['name_patterns']==['*']
    assert p['suggested_tool_call']['arguments']['payload']['params']['roots']==['/tmp/exams']
    s.events.append(ready().events[2])
    p=model_progress(s, tools(('libreoffice_writer','document.read_file')))
    assert p['suggested_tool_call']['arguments']['payload']['params']['path']=='/tmp/exams/Reference.docx'
    assert 'READ ONLY' in p['source_protection']


def test_per_student_projection_preserves_existing_and_never_supplies_scores():
    s=ready()
    p=model_progress(s, tools(('libreoffice_calc','range.write')))
    assert p['stage']=='compare_one_student_and_write'
    assert p['current_row']['cell_addresses']==['A3','B3','C3','D3','E3']
    assert p['current_student_source'][0]['text'].startswith('Student ID: 18')
    assert p['existing_graded_rows'][0]['display_text'][0]=='17'
    assert 'suggested_tool_call' not in p
    assert p['remaining_rows_with_blank_scores']==1


def test_write_read_save_read_does_not_repeat_or_forget_completed_rows():
    s=ready()
    s.events.append(event(6,'libreoffice_calc','range.write', params={'range':'C3:E3','values':[[0,1,5]]}))
    assert model_progress(s,tools(('libreoffice_calc','range.read')))['stage']=='read_live_target'
    s.events.append(event(7,'libreoffice_calc','range.read',{**table(False), 'range':'A1:E3'}))
    assert model_progress(s,tools(('libreoffice_calc','workbook.save')))['stage']=='save_target'
    s.events.append(event(8,'libreoffice_calc','workbook.save'))
    assert model_progress(s,tools(('libreoffice_calc','workbook.read_file')))['stage']=='read_saved_target'
    s.events.append(event(9,'libreoffice_calc','workbook.read_file',{'sheets':[table(False)]}))
    assert model_progress(s,tools())['stage']=='verify_completion'


@pytest.mark.parametrize('mode',[{}, {'protocol_recovery':True},{'execution_recovery':True}])
def test_actual_messages_keep_concrete_guidance_tools_and_events(mode):
    s=ready()
    ts=tools(('libreoffice_calc','range.write'))
    before=deepcopy((s.events,ts))
    a=LiteAgent(LiteAgentConfig(base_url='http://unused',include_gui=False), SimpleNamespace(), model_client=SimpleNamespace(client=object()))
    ms=a._messages(s,b'png',tools=ts,**mode)
    assert 'Current grading step' in ms[0]['content']
    assert 'current_student_source' in ms[-1]['content'][0]['text']
    assert (s.events,ts)==before


def test_unrelated_and_non_grading_requests_do_not_trigger():
    s=ready()
    s.instruction='Copy students answers to a new document.'
    assert model_progress(s) is None


def test_raw_answer_pairs_are_observed_letters_not_generated_scores():
    s=ready()
    s.events[3]=read(4, '/tmp/exams/Reference.docx', 'Reference: 5 points per question\n【Answer】A\n【Answer】B')
    s.events[4]=read(5, '/tmp/exams/student.docx', 'Student ID: 18 Bea\n【Answer】C\n【Answer】B')
    p=model_progress(s, tools(('libreoffice_calc','range.write')))
    assert p['raw_answer_pairs']==[
        {'source_position':1,'column_header':'Q1','target_cell':'C3','reference_answer':'A','student_answer':'C'},
        {'source_position':2,'column_header':'Q2','target_cell':'D3','reference_answer':'B','student_answer':'B'}]
    assert 'score' not in p['raw_answer_pairs'][0]


def test_unsaved_disk_preview_does_not_invalidate_need_for_live_read():
    s=ready()
    s.events.append(event(6,'libreoffice_calc','range.write',params={'range':'C3:E3','values':[[0,1,5]]}))
    s.events.append(event(7,'libreoffice_calc','workbook.read_file',{'sheets':[table()]}))
    p=model_progress(s, tools(('libreoffice_calc','range.read')))
    assert p['stage']=='read_live_target'
    assert p['suggested_tool_call']['arguments']['payload']['params']['range']=='A1:E3'


def test_total_formula_guidance_has_no_embedded_points_or_formula_answer():
    p=model_progress(ready(),tools(('libreoffice_calc','range.write')))
    assert 'Do not hand-count' in p['next_step']
    assert 'SUM' in p['next_step']
    assert '=SUM' not in str(p)
    assert 'suggested_tool_call' not in p


def test_write_contract_keeps_actual_sheet_markers_and_total_cell_after_table_compaction():
    p=model_progress(ready(),tools(('libreoffice_calc','range.write')))
    assert 'table' not in p
    assert p['write_contract']['sheet']=='Scores'
    assert p['write_contract']['question_range']=='C3:D3'
    assert p['write_contract']['total_cells']==['E3']
    assert p['write_contract']['observed_existing_question_marker_values']==['0','1']
    assert '5' not in p['write_contract']['observed_existing_question_marker_values']
