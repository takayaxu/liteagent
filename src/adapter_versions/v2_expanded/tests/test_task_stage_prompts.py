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


def test_bound_context_requires_exact_task_and_single_empty_input_tool():
    from integrations.lite_agent.task_stage_prompts import bound_call_context
    stages = {'target': [{'when_tool': 'bound', 'text': 'Serialize the current call.',
                          'context_mode': 'bound_call'}]}
    tool = {'type': 'function', 'function': {'name': 'bound', 'parameters': {
        'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}}}
    state = RuntimeState(task_id='target', domain='os', instruction='Edit the file.')
    assert 'Emit one tool call with {}' in bound_call_context(stages, state, [tool])
    assert bound_call_context(stages, state, [tool, tool]) is None
    tool['function']['parameters']['properties'] = {'path': {'type': 'string'}}
    assert bound_call_context(stages, state, [tool]) is None
    state.task_id = 'different'
    assert bound_call_context(stages, state, [tool]) is None


def test_stage_recognizes_owner_qualified_actions_through_multi_apps_wrapper():
    stages = {'target': [{'after_action': 'thunderbird:contacts.export_csv',
                          'until_action': 'os:desktop.open_path', 'text': 'Open the observed CSV.'}]}
    state = RuntimeState(task_id='target', domain='multi_apps', instruction='Convert the exported data.')
    def add(owner, action):
        state.events.append(ExecutionEvent(step=len(state.events)+1, timestamp_utc='test',
            proposed={'kind': 'adapter', 'action': 'adapter.call', 'arguments': {
                'adapter': owner, 'action': action, 'payload': {'params': {}}}}, executed=True))
    assert stage_prompt_text(stages, state, []) == ''
    add('thunderbird', 'contacts.export_csv')
    assert stage_prompt_text(stages, state, []) == 'Open the observed CSV.'
    add('os', 'desktop.open_path')
    assert stage_prompt_text(stages, state, []) == ''


def test_stage_predicates_canonicalize_public_save_aliases():
    stages = {'target': [{'after_action': 'libreoffice_calc:workbook.save_as', 'text': 'Read saved output.'}]}
    state = RuntimeState(task_id='target', domain='multi_apps', instruction='Convert the data.')
    state.events.append(ExecutionEvent(step=1, timestamp_utc='test', executed=True,
        proposed={'kind': 'adapter', 'action': 'adapter.call', 'arguments': {
            'adapter': 'libreoffice_calc', 'action': 'workbook.save_as', 'payload': {'params': {}}}}))
    assert stage_prompt_text(stages, state, []) == 'Read saved output.'


def test_unknown_qualified_action_is_rejected_before_prompt_selection():
    with pytest.raises(ValueError, match='unknown qualified stage action'):
        LiteAgentConfig(base_url='http://unused', task_stage_prompts={
            'target': [{'after_action': 'os:archive.create', 'text': 'Inspect output.'}]})


def test_copy_facts_keep_opened_and_verified_copied_images_distinct():
    from integrations.lite_agent.task_stage_prompts import stage_fact_text
    stages = {'target': [{'text': 'Check current evidence.', 'facts': 'file_copy_ledger'}]}
    state = RuntimeState(task_id='target', domain='multi_apps', instruction='Select images.')
    def add(action, params, executed=True, verified=True):
        state.events.append(ExecutionEvent(step=len(state.events)+1, timestamp_utc='test',
            proposed={'kind': 'adapter', 'action': 'adapter.call', 'arguments': {
                'adapter': 'os', 'action': action, 'payload': {'params': params}}},
            executed=executed, result={'verification_passed': verified}))
    add('desktop.open_path', {'path': '/tmp/opened.jpg'})
    add('filesystem.copy', {'source': '/tmp/opened.jpg', 'destination': '/tmp/dst/opened.jpg'}, executed=False)
    add('filesystem.copy', {'source': '/tmp/unverified.jpg', 'destination': '/tmp/dst/unverified.jpg'}, verified=False)
    add('filesystem.copy', {'source': '/tmp/copied.jpg', 'destination': '/tmp/dst/copied.jpg'})
    text = stage_fact_text(stages, state, [])
    import json
    data = json.loads(text.split('CURRENT EXECUTED COPY FACTS: ', 1)[1].split('\n', 1)[0])
    assert data['opened_image_paths'] == ['/tmp/opened.jpg']
    assert data['verified_executed_copies'] == [{'source': '/tmp/copied.jpg', 'destination': '/tmp/dst/copied.jpg'}]
    assert data['verified_copy_count'] == 1
    assert 'unverified.jpg' not in text
    state.task_id = 'different'
    assert stage_fact_text(stages, state, []) == ''


@pytest.mark.parametrize('recovery', [{}, {'protocol_recovery': True}, {'execution_recovery': True}])
def test_copy_fact_projection_does_not_change_other_task_requests(recovery):
    stages = {'target': [{'when_tool': 'gui_action', 'text': 'Check copies.', 'facts': 'file_copy_ledger'}]}
    def agent(prompts):
        return LiteAgent(LiteAgentConfig(base_url='http://unused', task_stage_prompts=prompts),
                         SimpleNamespace(), model_client=SimpleNamespace(client=None))
    baseline, candidate = agent(None), agent(stages)
    state = RuntimeState(task_id='different', domain='os', instruction='Inspect images.')
    tools = build_tools('os', [], include_gui=True)
    assert candidate._messages(state, b'synthetic', tools=tools, **recovery) == baseline._messages(state, b'synthetic', tools=tools, **recovery)
    state.task_id = 'target'
    messages = candidate._messages(state, b'synthetic', tools=tools, **recovery)
    assert 'CURRENT EXECUTED COPY FACTS:' in messages[-1]['content'][0]['text']


def test_pdf_source_facts_preserve_omitted_rows_exact_names_and_verified_receipts():
    import json
    from integrations.lite_agent.task_stage_prompts import stage_fact_text
    state = RuntimeState(task_id='target', domain='multi_apps', instruction='Transfer source data.')
    stages = {'target': [{'text': 'Use observed source.', 'facts': 'pdf_source_ledger'}]}
    def add(owner, action, params, result, executed=True):
        state.events.append(ExecutionEvent(step=len(state.events)+1, timestamp_utc='test',
            proposed={'kind': 'adapter', 'action': 'adapter.call', 'arguments': {
                'adapter': owner, 'action': action, 'payload': {'params': params}}},
            executed=executed, result={'verification_passed': True, **result}))
    add('libreoffice_calc', 'workbook.read_file', {'path': '/source.xlsx'}, {
        'context_hint': {'downstream_context': {'sheets': [{'display_text': [['preview']]}]}},
        'adapter_response': {'result': {'path': '/source.xlsx', 'sheets': [
            {'name': 'Sheet1', 'returned_range': 'A1:A2', 'display_text': [['preview'], ['omitted row']]}]}}})
    add('os', 'pdf.form.inspect', {'input_path': '/template.pdf'}, {
        'context_hint': {'downstream_context': {'input_path': '/template.pdf', 'fields': [
            {'field_name': 'ExactRow1', 'label': 'Exact_Row_1'},
            {'field_name': 'Signature', 'field_type': '/Sig', 'writable': False}]}},
        'adapter_response': {'truncated': True, 'preview': 'invalid JSON'}})
    add('os', 'pdf.form.fill', {'input_path': '/template.pdf', 'output_path': '/done.pdf',
        'fields': [{'field_name': 'ExactRow1', 'value': 'observed'}]}, {})
    add('os', 'pdf.form.fill', {'output_path': '/failed.pdf'}, {}, executed=False)
    text = stage_fact_text(stages, state, [])
    facts = json.loads(text.split('CURRENT PDF SOURCE FACTS: ', 1)[1].split('\n')[0])
    assert facts['observed_workbook_reads'][0]['sheets'][0]['display_text'][-1] == ['omitted row']
    assert facts['observed_workbook_reads'][0]['sheets'][0]['source_rows_by_header'] == [{'preview': 'omitted row'}]
    assert facts['observed_pdf_fields'][0]['fields'] == [
        {'field_name': 'ExactRow1'}, {'field_name': 'Signature', 'field_type': '/Sig', 'writable': False}]
    assert facts['verified_executed_fills'][0]['output_path'] == '/done.pdf'
    assert 'Exact_Row_1' not in text and '/failed.pdf' not in text
    state.task_id = 'other'
    assert stage_fact_text(stages, state, []) == ''


@pytest.mark.parametrize('recovery', [{}, {'protocol_recovery': True}, {'execution_recovery': True}])
def test_pdf_facts_do_not_change_other_task_messages(recovery):
    stages = {'target': [{'text': 'Use observed source.', 'facts': 'pdf_source_ledger'}]}
    def agent(prompts):
        return LiteAgent(LiteAgentConfig(base_url='http://unused', task_stage_prompts=prompts),
                         SimpleNamespace(), model_client=SimpleNamespace(client=None))
    state = RuntimeState(task_id='other', domain='os', instruction='Inspect a file.')
    tools = build_tools('os', [], include_gui=True)
    assert agent(stages)._messages(state, b'synthetic', tools=tools, **recovery) == agent(None)._messages(state, b'synthetic', tools=tools, **recovery)


def test_source_header_view_never_collapses_duplicate_or_incomplete_columns():
    from integrations.lite_agent.task_stage_prompts import _source_sheet_facts
    for rows in ([["same", "same"], ["first", "second"]], [["one", "two"], ["short"]]):
        facts = _source_sheet_facts({"display_text": rows})
        assert facts["display_text"] == rows
        assert "source_rows_by_header" not in facts
