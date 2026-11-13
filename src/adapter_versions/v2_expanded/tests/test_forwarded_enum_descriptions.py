from copy import deepcopy
import json

import pytest

from integrations.lite_agent import search_recovery_tools
from integrations.lite_agent.tool_catalog import DIRECT_ACTION_SCHEMAS, build_tools


def test_impress_export_keeps_native_enum_alongside_descriptive_contract():
    schema = deepcopy(DIRECT_ACTION_SCHEMAS['libreoffice_impress']['presentation.export'])
    description = search_recovery_tools._flat_route_description('libreoffice_impress', 'presentation.export')
    assert json.dumps(schema['properties']['format']['enum']) in description
    assert 'Output representation' in description
    assert DIRECT_ACTION_SCHEMAS['libreoffice_impress']['presentation.export'] == schema
    tools = search_recovery_tools.constrain_adapter_call_routes(
        build_tools('multi_apps', ['adapter.call'], include_gui=False),
        [('libreoffice_impress', 'presentation.export'), ('libreoffice_impress', 'presentation.inspect')],
    )
    params = next(t['function']['parameters'] for t in tools if t['function']['name'] == 'adapter__adapter_call')
    assert json.dumps(schema['properties']['format']['enum']) in params['properties']['payload']['properties']['params']['description']


@pytest.mark.parametrize('enum', [[True, False], list(range(100)), ['short', 'last member']])
def test_long_field_description_does_not_drop_or_truncate_enum(monkeypatch, enum):
    schema = {'properties': {'choice': {'enum': enum, 'description': 'x' * 400}}, 'required': ['choice']}
    monkeypatch.setattr(search_recovery_tools, '_downstream_params_schema', lambda *_: deepcopy(schema))
    description = search_recovery_tools._flat_route_description('owner', 'operation')
    assert 'allowed values ' + json.dumps(enum) in description
