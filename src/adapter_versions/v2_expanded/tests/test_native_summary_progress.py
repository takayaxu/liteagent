from copy import deepcopy
from types import SimpleNamespace

import pytest

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.native_summary_progress import model_progress
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


def event(step, action, body=None, *, wrapped=False, executed=True):
    proposed = {'kind': 'adapter', 'action': action, 'arguments': {}}
    result = {'result': body or {}}
    if wrapped:
        proposed.update(action='adapter.call', arguments={
            'adapter': 'libreoffice_impress', 'action': action, 'payload': {'params': {}}})
        result = {'context_hint': {'downstream_context': body or {}}}
    return ExecutionEvent(step=step, timestamp_utc='', proposed=proposed,
                          result=result, executed=executed)


def state(*events):
    return RuntimeState(task_id='synthetic', domain='libreoffice_impress',
                        instruction='Make a native summary slide.', events=list(events))


def created(step=1, **overrides):
    return event(step, 'slides.create_summary', {
        'created_slide_indices': [3], 'effective_source_slides': [0, 1, 2],
        'native_summary_bodies': ['Overview\nFindings'], 'summary_empty': False,
        'source_titles_match': True, 'original_slide_count': 3,
        'source_preservation': {'page_summary_unchanged': True}, **overrides})


def inspected(step=3, **overrides):
    return event(step, 'presentation.inspect', {
        'slide_count': 4, 'slides': [{'slide': 3, 'text_shapes': [{
            'kind': 'com.sun.star.presentation.OutlinerShape',
            'paragraphs': [{'text': 'Overview'}, {'text': 'Findings'}]}]}], **overrides}, wrapped=True)


def test_creation_save_readback_and_no_repeated_verification():
    s = state(created())
    ts = [{'function': {'name': 'adapter__presentation_save'}}]
    p = model_progress(s, ts)
    assert p['stage'] == 'save_created_summary'
    assert p['suggested_tool_call'] == {'name': 'adapter__presentation_save', 'arguments': {}}
    s.events.append(event(2, 'presentation.save'))
    p = model_progress(s, [{'function': {'name': 'adapter__presentation_inspect'}}])
    assert p['suggested_tool_call']['arguments'] == {'slides': [3]}
    s.events.append(inspected())
    snapshot = deepcopy(s)
    for _ in range(3):
        p = model_progress(s, ts)
        assert p['stage'] == 'review_remaining_clauses'
        assert p['readback_differences'] == []
        assert 'propose_done now' in p['next_step']
    assert s == snapshot


def test_unrelated_or_unexecuted_creation_does_not_activate():
    assert model_progress(state(event(1, 'presentation.inspect'))) is None
    e = created()
    e.executed = False
    assert model_progress(state(e)) is None
    e.executed = True
    e.error = {'detail': 'failed'}
    assert model_progress(state(e)) is None


@pytest.mark.parametrize('action', ['shape.write_text', 'slides.delete'])
def test_later_document_mutation_invalidates_completion_hint(action):
    assert model_progress(state(created(), event(2, action))) is None


def test_gui_invalidates_and_failed_mutation_does_not_invalidate():
    s = state(created(), event(2, 'shape.write_text', executed=False))
    assert model_progress(s)['stage'] == 'save_created_summary'
    s.events.append(ExecutionEvent(step=3, timestamp_utc='', executed=True,
                                  proposed={'kind': 'gui', 'arguments': {'action': 'type'}}))
    assert model_progress(s) is None


def test_readback_of_source_does_not_count_as_generated_page():
    s = state(created(), event(2, 'presentation.save'), inspected(slides=[{'slide': 1}]))
    assert model_progress(s)['stage'] == 'read_created_summary'


@pytest.mark.parametrize('overrides', [{'summary_empty': True}, {'source_titles_match': False}])
def test_empty_or_unmatched_native_result_never_gets_completion_hint(overrides):
    assert model_progress(state(created(**overrides)))['stage'] == 'assess_native_result'


def test_incomplete_body_and_unexpected_page_count_are_reported():
    s = state(created(), event(2, 'presentation.save'), inspected(slide_count=5,
        slides=[{'slide': 3, 'text_shapes': []}]))
    p = model_progress(s)
    assert p['stage'] == 'assess_readback'
    assert len(p['readback_differences']) == 2


def test_duplicate_creation_is_exposed_instead_of_endorsed():
    s = state(created(), created(2, created_slide_indices=[4]))
    p = model_progress(s)
    assert p['stage'] == 'assess_duplicate_creation'
    assert p['previously_created_slide_indices'] == [[3]]
    assert p['created_slide_indices'] == [4]


@pytest.mark.parametrize('mode', [{}, {'protocol_recovery': True}, {'execution_recovery': True}])
def test_real_message_builder_keeps_stage_and_leaves_tools_events_unchanged(mode):
    s = state(created(), event(2, 'presentation.save'), inspected())
    tools = [{'type': 'function', 'function': {'name': 'propose_done',
        'parameters': {'type': 'object', 'properties': {}}}}]
    before = deepcopy((s.events, tools))
    agent = LiteAgent(LiteAgentConfig(base_url='http://unused', include_gui=False),
                      SimpleNamespace(), model_client=SimpleNamespace(client=object()))
    messages = agent._messages(s, b'png', tools=tools, **mode)
    content = str(messages)
    assert 'Current native-summary step' in content
    assert 'review_remaining_clauses' in content
    assert 'current_completion_status' in content
    assert (s.events, tools) == before
