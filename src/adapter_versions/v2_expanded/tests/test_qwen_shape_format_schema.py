"""The generation grammar must require a real format without rewriting calls."""
from copy import deepcopy
import itertools
import json
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from impress_adapter.schema import parse_action_request
from integrations.lite_agent.atomic_tool_surface import atomic_provider_surface, restore_adapter_arguments
from integrations.lite_agent.model_client import (
    QWEN_TOOL_CALL_END, StructuredToolModelClient, StructuredToolProtocolError,
    _qwen_schema_compatible_tools,
)
from integrations.lite_agent.qwen_shape_format_schema import (
    FORMAT_FIELDS, UnsupportedShapeFormatSchema, lower_shape_format_schemas,
)
from integrations.lite_agent.tool_catalog import build_tools


TARGET = {"slide": 0, "selector": {"path": [1]}}
VALUES = {"color": 0, "font_size": 12, "font_name": "Arial", "bold": False,
          "italic": False, "underline": False, "strike": False, "alignment": "left",
          "bullet": False, "level": 0, "left_margin": 0, "first_line_indent": -10}


def shape_tools():
    return build_tools("libreoffice_impress", ["shape.format_text"], include_gui=False,
                       include_control_tools=False, strict_generic=True)


def schemas():
    tools = shape_tools()
    return (tools[0]["function"]["parameters"],
            _qwen_schema_compatible_tools("Qwen3.5-9B", tools)[0]["function"]["parameters"])


def cases():
    yield "target_only", TARGET, False
    yield "scope_without_format", {**TARGET, "match_text": "Example", "lines": [0]}, False
    for field, value in VALUES.items():
        yield field, {**TARGET, field: value}, True
    for value in ["#aBc123", "red", 16777215]:
        yield f"color_{value}", {**TARGET, "color": value}, True
    yield "whole_shape", {**TARGET, "bullet": False, "level": 0}, True
    yield "literal", {**TARGET, "bold": False, "match_text": "Example"}, True
    yield "lines", {**TARGET, "bullet": False, "lines": [0, 2]}, True
    yield "legacy_both_scopes", {**TARGET, "bullet": False, "match_text": "Example", "lines": [0]}, True
    for key, value in [("color", -1), ("color", 16777216), ("color", "invalid-color"),
                       ("font_size", 0), ("level", -1), ("bullet", 0), ("lines", []),
                       ("lines", [-1]), ("match_text", ""), ("extra", True)]:
        yield f"invalid_{key}_{value}", {**TARGET, "bold": False, key: value}, False
    yield "missing_slide", {"selector": {"path": [1]}, "bold": False}, False
    yield "empty_selector", {**TARGET, "selector": {}, "bold": False}, False


@pytest.mark.parametrize("label,args,expected", list(cases()))
def test_public_generation_and_owner_agree(label, args, expected):
    for schema in schemas():
        assert Draft202012Validator(schema).is_valid(args) == expected, label
    if expected:
        assert parse_action_request({"action": "shape.format_text", "params": args}).params == args


def test_every_nonempty_format_combination_matches_exactly_one_complete_branch():
    public, wire = schemas()
    source = Draft202012Validator(public)
    validator = Draft202012Validator(wire)
    branches = [Draft202012Validator(branch) for branch in wire["oneOf"]]
    count = 0
    for size in range(1, len(FORMAT_FIELDS) + 1):
        for fields in itertools.combinations(FORMAT_FIELDS, size):
            args = {**TARGET, **{field: VALUES[field] for field in fields}, "lines": [0, 2]}
            assert source.is_valid(args)
            assert validator.is_valid(args)
            assert sum(branch.is_valid(args) for branch in branches) == 1
            count += 1
    assert count == 4095


@pytest.mark.parametrize("keyword,value", [("maxProperties", 4), ("not", {"required": ["lines"]}),
                                         ("required", ["slide"]), ("anyOf", [{"required": ["lines"]}])])
def test_unknown_contract_fails_closed(keyword, value):
    tools = shape_tools()
    tools[0]["function"]["parameters"][keyword] = value
    with pytest.raises(UnsupportedShapeFormatSchema):
        _qwen_schema_compatible_tools("Qwen3.5-9B", tools)


def test_nested_schema_positions_are_lowered_but_literals_and_other_models_are_untouched():
    public, _ = schemas()
    wrapper = {"type": "function", "function": {"name": "adapter__adapter_call", "parameters": {
        "type": "object", "properties": {"payload": {"type": "object", "properties": {
            "params": public}, "required": ["params"], "additionalProperties": False},
            "literal": {"const": public}, "default": {"type": "string"}},
        "required": ["payload"], "additionalProperties": False}}}
    tools = [wrapper]
    original = deepcopy(tools)
    wire = lower_shape_format_schemas(tools)[0]["function"]["parameters"]
    assert tools == original
    assert "oneOf" in wire["properties"]["payload"]["properties"]["params"]
    assert wire["properties"]["literal"]["const"] == public
    Draft202012Validator(wire).validate({"payload": {"params": {**TARGET, "bullet": False}}})
    assert not Draft202012Validator(wire).is_valid({"payload": {"params": TARGET}})
    assert _qwen_schema_compatible_tools("another-model", tools) is tools
    unrelated = build_tools("libreoffice_impress", ["shape.set_geometry"], include_gui=False,
                            strict_generic=True)
    assert lower_shape_format_schemas(unrelated) == unrelated


def test_existing_atomic_projection_keeps_optional_request_metadata():
    public, _ = schemas()
    tools = [{"type": "function", "function": {"name": "adapter__adapter_call", "parameters": {
        "type": "object", "x-route": {"adapter": "libreoffice_impress", "action": "shape.format_text"},
        "properties": {"payload": {"type": "object", "properties": {"params": public,
            "timeout_ms": {"type": "integer", "minimum": 1}},
            "required": ["params"], "additionalProperties": False}},
        "required": ["payload"], "additionalProperties": False}}}]
    projected, bindings = atomic_provider_surface(tools)
    assert len(bindings) == 1
    wire = _qwen_schema_compatible_tools("Qwen3.5-9B", projected)[0]["function"]["parameters"]
    args = {**TARGET, "bullet": False, "request_options": {"timeout_ms": 4000}}
    Draft202012Validator(wire).validate(args)
    assert not Draft202012Validator(wire).is_valid({**TARGET, "request_options": {"timeout_ms": 4000}})
    binding = next(iter(bindings.values()))
    assert restore_adapter_arguments(args, binding)["payload"] == {
        "params": {**TARGET, "bullet": False}, "timeout_ms": 4000}


@pytest.mark.parametrize("valid", [True, False])
def test_real_client_validates_original_contract_and_preserves_raw_arguments(valid):
    tools = shape_tools()
    args = {**TARGET, "match_text": "Example", "lines": [0]}
    if valid:
        args.update(bullet=False, level=0, first_line_indent=-10)
    raw = json.dumps(args)
    requests = []

    def create(**request):
        requests.append(request)
        return SimpleNamespace(model="Qwen3.5-9B", usage=None, choices=[SimpleNamespace(
            finish_reason="tool_calls", message=SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                id="1", function=SimpleNamespace(name="adapter__shape_format_text", arguments=raw))]))])

    client = StructuredToolModelClient(base_url="http://unused", api_key="EMPTY", request_timeout_seconds=1,
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    kwargs = dict(model="Qwen3.5-9B", messages=[], tools=tools, temperature=0,
                  output_token_budget=1024, enable_thinking=True)
    if valid:
        result = client.propose(**kwargs)
        assert result["arguments_raw"] == result["provider_arguments_raw"] == raw
    else:
        with pytest.raises(StructuredToolProtocolError) as error:
            client.propose(**kwargs)
        assert any("allowed field set" in hint for hint in error.value.schema_hints)
    assert "oneOf" in requests[0]["tools"][0]["function"]["parameters"]
    assert "anyOf" in tools[0]["function"]["parameters"]


def test_actual_xgrammar_requires_format_and_retains_legal_value_paths():
    xgr = pytest.importorskip("xgrammar")
    _, schema = schemas()
    begin = "<tool_call>\n<function=adapter__shape_format_text>\n"
    tag = {"type": "tag", "begin": begin, "content": {"type": "json_schema", "json_schema": schema,
           "style": "qwen_xml", "any_order": False}, "end": QWEN_TOOL_CALL_END}
    compiler = xgr.GrammarCompiler(xgr.TokenizerInfo(
        [bytes([i]) for i in range(256)] + [b"<eos>"], stop_token_ids=[256]), max_threads=1)
    grammar = compiler.compile_grammar(xgr.Grammar.from_structural_tag({"type": "structural_tag", "format": tag}))
    for label, args, expected in cases():
        parts = []
        for key in [*schema["properties"], *(key for key in args if key not in schema["properties"])]:
            if key not in args:
                continue
            value = args[key]
            # Union-valued colors use the XML string representation too; the
            # authoritative JSON validator still checks the parser's value.
            raw = value if isinstance(value, str) else json.dumps(value)
            parts.append(f"<parameter={key}>\n{raw}\n</parameter>")
        matcher = xgr.GrammarMatcher(grammar)
        accepted = matcher.accept_string(begin + "\n".join(parts) + QWEN_TOOL_CALL_END)
        # XML delimiter newlines can satisfy string minLength before the
        # provider strips them. This existing ambiguity still fails the public
        # validator above; generation is never a replacement for that check.
        grammar_expected = True if label == "invalid_match_text_" else expected
        assert bool(accepted and matcher.is_completed()) == grammar_expected, label
