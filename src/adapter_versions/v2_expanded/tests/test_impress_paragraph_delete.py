"""Public contract for a selected paragraph, including empty paragraphs."""
import jsonschema
import pytest

from impress_adapter.errors import AdapterError
from impress_adapter.schema import parse_action_request
from impress_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
from impress_adapter.uno_worker import ACTIONS
from integrations.lite_agent.tool_catalog import DIRECT_ACTION_SCHEMAS


ACTION = 'shape.delete_paragraph'
PARAMS = {'slide': 2, 'selector': {'path': [1]}, 'paragraph_index': 3, 'expected_text': ''}


def test_empty_paragraph_contract_agrees_across_public_native_and_dispatch():
    schema = STRICT_ACTION_PARAM_SCHEMAS[ACTION]
    assert DIRECT_ACTION_SCHEMAS['libreoffice_impress'][ACTION] == schema
    jsonschema.validate(PARAMS, schema)
    assert parse_action_request({'action': ACTION, 'params': PARAMS}).params == PARAMS
    assert ACTION in ACTIONS
    assert 'paragraphs[].index' in schema['description']


@pytest.mark.parametrize('override', [
    {'paragraph_index': True}, {'paragraph_index': -1}, {'paragraph_index': '3'},
    {'expected_text': None}, {'lines': [3]},
])
def test_native_validation_rejects_invalid_or_unrelated_fields(override):
    with pytest.raises(AdapterError):
        parse_action_request({'action': ACTION, 'params': {**PARAMS, **override}})
