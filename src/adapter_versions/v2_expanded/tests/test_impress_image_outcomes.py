"""Final picture contents and object inventory, independent of cleanup strategy."""
from types import SimpleNamespace

import pytest

from impress_adapter import uno_worker
from impress_adapter.errors import AdapterError
from impress_adapter.schema import validate_action_params
from integrations.lite_agent.adapter_results import adapter_context_hint, compact_presentation_hint_for_model
from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.completion import CompletionMixin
from integrations.lite_agent.completion_outcomes import completion_outcome_issues
from integrations.lite_agent.impress_image_outcomes import picture_deck_spec
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


URL = 'file:///tmp/slideshow.pptx'
INSTRUCTION = 'Create two blank slides with one image per slide in numerical order using scene7.png to scene8.png.'


def fingerprint(index):
    return {'status': 'known', 'algorithm': 'sha256-native-dib-v1',
            'sha256': f'{index:064x}', 'pixel_width': 32, 'pixel_height': 24}


def picture(index):
    return {'index': 0, 'path': [0], 'name': 'An editable object name',
            'kind': 'com.sun.star.drawing.GraphicObjectShape', 'visible': True,
            'width': 2000, 'height': 2000, 'graphic_fingerprint': fingerprint(index)}


def event(step, action, result=None, args=None):
    return ExecutionEvent(step=step, timestamp_utc='2030-01-01T00:00:00Z',
                          proposed={'kind': 'adapter', 'action': action, 'arguments': args or {}},
                          parsed=True, validated=True, executed=True,
                          result={'adapter_response': {'result': result or {}}})


def inventory():
    return {'identity': {'url': URL}, 'slide_count': 2, 'inspected_slides': [0, 1],
            'source_images': [{'source_path': f'/tmp/scene{i + 7}.png', 'graphic_fingerprint': fingerprint(i)} for i in range(2)],
            'slides': [{'index': i, 'shape_count': 1, 'shapes': [picture(i)]} for i in range(2)]}


def state():
    return RuntimeState(task_id='synthetic-image-deck', domain='libreoffice_impress', instruction=INSTRUCTION,
                        events=[event(1, 'slide.create', args={'layout': 20}),
                                event(2, 'presentation.save', {'url': URL}, {'url': URL}),
                                event(3, 'presentation.inspect', inventory())])


def codes(current):
    return {issue['code'] for issue in completion_outcome_issues(current)}


def test_clean_final_inventory_proves_counts_content_and_order():
    assert codes(state()) == set()


@pytest.mark.parametrize('extra', [
    {'kind': 'com.sun.star.presentation.TitleTextShape', 'text': ''},
    {'kind': 'com.sun.star.presentation.SubTitleShape', 'text': ''},
    {'kind': 'com.sun.star.drawing.RectangleShape'}, picture(0),
])
def test_any_extra_object_even_an_empty_placeholder_blocks_completion(extra):
    current = state()
    page = current.events[-1].result['adapter_response']['result']['slides'][0]
    page['shapes'].append(extra)
    page['shape_count'] += 1
    assert 'image_deck.extra_or_missing_objects' in codes(current)
    assert not CompletionMixin._generic_completion_gate(current)['passed']


@pytest.mark.parametrize('mode', ['wrong_order', 'renamed_wrong_image', 'unknown', 'invisible', 'empty', 'nonpicture'])
def test_picture_names_cannot_hide_wrong_or_unverified_content(mode):
    current = state()
    shape = current.events[-1].result['adapter_response']['result']['slides'][0]['shapes'][0]
    if mode in {'wrong_order', 'renamed_wrong_image'}:
        shape['graphic_fingerprint'] = fingerprint(1)
        shape['name'] = 'scene7.png'
        expected = 'content_order_mismatch'
    elif mode == 'unknown':
        shape['graphic_fingerprint'] = {'status': 'unknown'}
        expected = 'content_unverified'
    elif mode in {'invisible', 'empty'}:
        shape.update({'visible': False} if mode == 'invisible' else {'width': 0})
        expected = 'picture_visibility'
    else:
        shape['kind'] = 'com.sun.star.drawing.TextShape'
        expected = 'picture_count'
    assert 'image_deck.' + expected in codes(current)


@pytest.mark.parametrize('action', ['shape.delete', 'presentation.save', 'slide.create'])
def test_read_before_last_write_or_save_is_stale(action):
    current = state()
    current.events.append(event(4, action))
    assert codes(current) == {'image_deck.slide_count'}
    current.events.append(event(5, 'presentation.inspect', inventory()))
    assert not codes(current)


def test_failed_dispatched_mutation_and_gui_invalidate_observations():
    current = state()
    failed = event(4, 'shape.delete')
    failed.executed = False
    failed.error = {'code': 'TIMEOUT'}
    current.events.append(failed)
    assert codes(current)
    current.events.append(event(5, 'presentation.inspect', inventory()))
    assert not codes(current)
    current.events.append(ExecutionEvent(step=6, timestamp_utc='', proposed={'kind': 'gui'}, executed=True))
    assert codes(current)


def test_partial_reads_can_cover_current_scope_and_latest_page_replaces_old():
    current = state()
    one = inventory()
    one['slides'] = one['slides'][:1]
    one['inspected_slides'] = [0]
    current.events[-1].result['adapter_response']['result'] = one
    assert 'image_deck.page_unobserved' in codes(current)
    two = inventory()
    two['slides'] = two['slides'][1:]
    two['inspected_slides'] = [1]
    current.events.append(event(4, 'presentation.inspect', two))
    assert not codes(current)
    one['slides'][0]['shape_count'] = 3
    current.events.append(event(5, 'presentation.inspect', one))
    assert 'image_deck.extra_or_missing_objects' in codes(current)


@pytest.mark.parametrize('marker', ['truncated', 'context_truncated', 'slides_omitted_from_context'])
def test_truncated_read_cannot_be_used_as_complete_inventory(marker):
    current = state()
    newer = inventory()
    newer[marker] = True
    current.events.append(event(4, 'presentation.inspect', newer))
    assert codes(current)


def test_cross_document_source_evidence_cannot_establish_order_but_save_as_can():
    current = state()
    newer = inventory()
    newer['identity']['url'] = 'file:///tmp/other.pptx'
    newer['source_images'] = []
    current.events.append(event(4, 'presentation.inspect', newer))
    assert 'image_deck.content_unverified' in codes(current)
    current = state()
    current.events.append(event(4, 'presentation.save', {'url': 'file:///tmp/other.pptx'}))
    current.events.append(event(5, 'presentation.inspect', newer))
    assert not codes(current)


def test_conflicting_source_paths_and_missing_total_remain_unknown():
    current = state()
    data = current.events[-1].result['adapter_response']['result']
    data['source_images'].append({'source_path': '/elsewhere/scene7.png', 'graphic_fingerprint': fingerprint(1)})
    assert 'image_deck.content_unverified' in codes(current)
    del data['slides'][0]['shape_count']
    del data['slides'][0]['shapes']
    assert 'image_deck.objects_unobserved' in codes(current)


def test_projected_inventory_preserves_counts_fingerprints_and_residual_selectors():
    raw = inventory()
    raw['slides'][0]['shapes'].append({'index': 1, 'path': [1], 'kind': 'TitleTextShape', 'is_text': True, 'text': ''})
    raw['slides'][0]['shape_count'] = 2
    hint = adapter_context_hint('libreoffice_impress', 'presentation.inspect', {'result': raw})
    compact = compact_presentation_hint_for_model(hint)
    assert compact['slides'][0]['shape_count'] == 2
    assert compact['slides'][0]['graphic_shapes'][0]['graphic_fingerprint'] == fingerprint(0)
    assert compact['slides'][0]['all_shapes'][1]['tool_target'] == {'slide': 0, 'selector': {'path': [1]}}
    assert compact['source_images'] == raw['source_images']
    current = state()
    current.events[-1].result = {'context_hint': compact}
    assert 'image_deck.extra_or_missing_objects' in codes(current)


def test_recovery_exposes_real_cleanup_and_observation_without_running_actions():
    current = state()
    current.events[-1].result['adapter_response']['result']['slides'][0]['shape_count'] = 3
    class NoExecution:
        def execute(self, *args):
            raise AssertionError('tool selection cannot perform cleanup')
    agent = LiteAgent(LiteAgentConfig(base_url='http://unused/v1', include_gui=False),
                      NoExecution(), model_client=SimpleNamespace(client=object()))
    names = {tool['function']['name'] for tool in agent.tools(current)}
    assert {'adapter__shape_delete', 'adapter__slide_delete', 'adapter__presentation_inspect',
            'adapter__presentation_save', 'adapter__shape_insert_image'} <= names


@pytest.mark.parametrize('instruction', [
    'Add two blank slides with one image per slide in order, scene7.png to scene8.png. Keep the others.',
    'Do not create two blank slides with one image per slide in numerical order, scene7.png to scene8.png.',
    'Create two blank slides with titles and pictures.',
    'Create two blank slides with one image per slide in order using scene7.png to scene8.png. Add a caption.',
    'Resize the pictures on slides 2 and 4.',
])
def test_other_or_negated_scopes_do_not_acquire_whole_deck_predicates(instruction):
    assert picture_deck_spec(instruction) is None


def test_alternative_count_prefix_extension_and_number_padding():
    spec = picture_deck_spec('Create 4 blank slides with one picture per slide in order: art03.jpg through art06.jpg.')
    assert spec == {'count': 4, 'names': ['art03.jpg', 'art04.jpg', 'art05.jpg', 'art06.jpg']}


@pytest.mark.parametrize('paths', [['relative.png'], ['https://host/a.png'], [''], 'not-a-list', ['/tmp/a.txt']])
def test_source_image_inspection_validates_paths_before_native_access(paths):
    with pytest.raises(AdapterError):
        validate_action_params('presentation.inspect', {'image_paths': paths})


def test_insertion_front_middle_append_and_failed_reorder_rollback(monkeypatch):
    original = object()
    class Pages:
        def __init__(self): self.items = [original]
        def getCount(self): return len(self.items)
        def getByIndex(self, i): return self.items[i]
        def insertNewByIndex(self, i):
            page = SimpleNamespace(Layout=0)
            self.items.insert(min(i + 1, len(self.items)), page)
            return page
        def remove(self, page): self.items.remove(page)
    pages = Pages()
    session = SimpleNamespace(pages=pages)
    def front(_session, page):
        pages.remove(page)
        pages.items.insert(0, page)
    monkeypatch.setattr(uno_worker, '_move_new_page_first', front)
    for params in ({'index': 0, 'layout': 20}, {'index': 1}, {}, {'index': 4}):
        before = list(pages.items)
        result = uno_worker._create_slide(session, params)
        index = params.get('index', len(before))
        assert result['index'] == index
        assert [p for i, p in enumerate(pages.items) if i != index] == before
    before = list(pages.items)
    monkeypatch.setattr(uno_worker, '_move_new_page_first', lambda *args: None)
    with pytest.raises(AdapterError):
        uno_worker._create_slide(session, {'index': 0})
    assert pages.items == before
