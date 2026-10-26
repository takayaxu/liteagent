from types import SimpleNamespace
import pytest
from jsonschema import validate
from writer_adapter import uno_worker as writer
from writer_adapter.errors import AdapterError
from writer_adapter.schema import validate_action_params
from writer_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
from integrations.lite_agent.tool_catalog import build_tools, search_actions
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes


@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
def test_source_file_append_preserves_unicode_newlines_existing_text_and_order(tmp_path, newline):
    class Text:
        String = 'Prefix:'
        def getEnd(self): return object()
        def createTextCursorByRange(self, end): return object()
        def insertString(self, cursor, value, absorb): self.String += value
    text = Text()
    session = SimpleNamespace(doc=SimpleNamespace(Text=text))
    source = tmp_path/'part.txt'
    content = f'第一行{newline}second\tline{newline}'
    source.write_bytes(content.encode())
    result = writer._append_text_file(session, {'path': str(source), 'separator': ''})
    assert text.String == 'Prefix:第一行\nsecond\tline\n'
    assert result['content_verified'] is True
    assert result['source_chars'] == len(content)
    writer._append_text_file(session, {'path': str(source), 'separator': '|next|'})
    assert text.String.endswith('|next|第一行\nsecond\tline\n')
    assert source.read_bytes() == content.encode()


@pytest.mark.parametrize('data', [b'\x00ABC', b'\xff\xff'])
def test_binary_or_invalid_text_is_rejected_before_mutation(tmp_path, data):
    path = tmp_path/'bad.txt'
    path.write_bytes(data)
    with pytest.raises(AdapterError):
        writer._append_text_file(SimpleNamespace(), {'path': str(path)})


def test_single_file_append_is_public_and_typed_without_batch_or_shell_fields():
    action = 'document.append_text_file'
    params = {'path': '/tmp/observed.txt', 'separator': ''}
    validate_action_params(action, params)
    validate(params, STRICT_ACTION_PARAM_SCHEMAS[action])
    tools = constrain_adapter_call_routes(build_tools('multi_apps', ['adapter.call'], include_gui=False), [('libreoffice_writer', action)])
    assert tools
    assert any(action in str(hit) for hit in search_actions('multi_apps', 'append text file verbatim Writer'))
    with pytest.raises(AdapterError):
        validate_action_params(action, {'paths': ['/tmp/a', '/tmp/b']})
