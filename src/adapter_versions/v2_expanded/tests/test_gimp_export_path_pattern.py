import copy

import pytest
from jsonschema import Draft202012Validator

from gimp_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
from integrations.lite_agent.atomic_tool_surface import atomic_provider_surface
from integrations.lite_agent.model_client import _qwen_schema_compatible_tools
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools


@pytest.mark.parametrize('path', ['', ' ', '\t\n', '/tmp/a.png', '/tmp/demo image.png',
                                 ' /tmp/a.png ', '/tmp/图.png', '/tmp/a\nb.png'])
def test_export_paths_keep_nonblank_search_semantics(path):
    schema = STRICT_ACTION_PARAM_SCHEMAS['image.export']
    for field in ('input_path', 'output_path'):
        revised = schema['properties'][field]
        original = {**copy.deepcopy(revised), 'pattern': r'\S'}
        assert Draft202012Validator(revised).is_valid(path) == Draft202012Validator(original).is_valid(path)
        assert revised['pattern'] == r'^[\s\S]*\S[\s\S]*$'


def test_export_provider_surface_receives_complete_path_pattern():
    tools = constrain_adapter_call_routes(build_tools('multi_apps', ['adapter.call'],
        include_gui=False, strict_generic=True), [('gimp', 'image.export')])
    projected, _ = atomic_provider_surface(tools)
    provider = _qwen_schema_compatible_tools('Qwen3.5-9B', projected)
    export = next(t['function'] for t in provider if 'gimp_image_export' in t['function']['name'])
    for field in ('input_path', 'output_path'):
        assert export['parameters']['properties'][field]['pattern'] == r'^[\s\S]*\S[\s\S]*$'
