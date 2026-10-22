from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from integrations.lite_agent.model_client import (
    QWEN_TOOL_CALL_END,
    StructuredToolModelClient,
    StructuredToolProtocolError,
    _bounded_qwen_empty_tool_constraint,
)


def _tools():
    return [
        {"type": "function", "function": {
            "name": "inspect", "parameters": {
                "type": "object", "properties": {}, "required": [],
                "additionalProperties": False,
            },
        }},
        {"type": "function", "function": {
            "name": "write", "parameters": {
                "type": "object", "properties": {"text": {"type": "string"}},
                "required": ["text"], "additionalProperties": False,
            },
        }},
    ]


def test_constraint_bounds_empty_body_and_retains_all_public_schemas():
    tools = _tools()
    before = deepcopy(tools)
    constraint = _bounded_qwen_empty_tool_constraint("Qwen3.5-9B", tools, QWEN_TOOL_CALL_END)
    fmt = constraint["format"]
    assert fmt["at_least_one"] and fmt["stop_after_first"]
    assert fmt["triggers"] == ["<tool_call>\n<function="]
    assert all(tag["begin"].count("\n") == 2 for tag in fmt["tags"])
    assert all(tag["end"] == "\n</function>\n</tool_call>" for tag in fmt["tags"])
    assert [tag["content"]["json_schema"] for tag in fmt["tags"]] == [
        tool["function"]["parameters"] for tool in tools
    ]
    assert [tag["content"]["max_whitespace_cnt"] for tag in fmt["tags"]] == [1, None]
    assert tools == before


@pytest.mark.parametrize(("model", "tools", "stop"), [
    ("other-model", _tools(), QWEN_TOOL_CALL_END),
    ("Qwen3.5-9B", _tools(), None),
    ("Qwen3.5-9B", _tools()[1:], QWEN_TOOL_CALL_END),
])
def test_constraint_only_applies_to_native_qwen_surfaces_with_empty_tools(model, tools, stop):
    assert _bounded_qwen_empty_tool_constraint(model, tools, stop) is None


@pytest.mark.parametrize(("name", "arguments", "count", "valid"), [
    ("inspect", {}, 1, True),
    ("inspect", {"unexpected": True}, 1, False),
    ("inspect", {}, 2, False),
    ("unknown", {}, 1, False),
    ("write", {"text": "  first\n\n  second  "}, 1, True),
])
def test_explicit_constraint_keeps_client_validation_and_argument_whitespace(
    name, arguments, count, valid,
):
    captured = []
    response = SimpleNamespace(model="Qwen3.5-9B", usage=None, choices=[
        SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(
            content=None, reasoning="Inspect the workspace.",
            tool_calls=[SimpleNamespace(id=str(i), function=SimpleNamespace(
                name=name, arguments=json.dumps(arguments),
            )) for i in range(count)],
        )),
    ])

    def create(**request):
        captured.append(request)
        return response

    client = StructuredToolModelClient(
        base_url="http://unused", api_key="EMPTY", request_timeout_seconds=1,
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    kwargs = dict(
        model="Qwen3.5-9B", messages=[], tools=_tools(), temperature=0,
        output_token_budget=8192, enable_thinking=True, reasoning_mode="thinking",
        tool_call_stop_sequence=QWEN_TOOL_CALL_END,
    )
    if valid:
        assert json.loads(client.propose(**kwargs)["arguments_raw"]) == arguments
    else:
        with pytest.raises(StructuredToolProtocolError):
            client.propose(**kwargs)
    request = captured[0]
    fmt = json.loads(request["extra_body"]["structured_outputs"]["structural_tag"])["format"]
    assert fmt["at_least_one"] and fmt["stop_after_first"]
    assert request["parallel_tool_calls"] is False
    assert request["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert request["max_tokens"] == 8192
