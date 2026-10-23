"""Generation and validation must agree on complete pivot contracts."""
from copy import deepcopy
import json
import re
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from calc_adapter.schema import A1_RANGE_PATTERN
from integrations.lite_agent.calc_percentage_outcomes import constrain_tool
from integrations.lite_agent.calc_pivot_layout import constrain_tool as constrain_layout
from integrations.lite_agent.model_client import (
    QWEN_TOOL_CALL_END, StructuredToolModelClient, StructuredToolProtocolError,
    _qwen_schema_compatible_tools,
)
from integrations.lite_agent.qwen_pivot_schema import (
    UnsupportedPivotSchema, _excluding_ranges, lower_pivot_schemas,
)
from integrations.lite_agent.tool_catalog import build_tools
from test_calc_percentage_outcomes import state


def pivot_tools(dynamic=True):
    current = state()
    tools = build_tools(current.domain, ["pivot.create"], include_gui=False, include_control_tools=False)
    if dynamic:
        constrain_tool(tools[0]["function"], current)
        constrain_layout(tools[0]["function"], current)
    return tools


def valid_args():
    return {
        "source_sheet": "Input", "source_range": "C4:E8", "destination_sheet": "Summary",
        "below_range": "H3:I6", "blank_rows": 1, "name": "ByZone", "row_fields": ["Zone"],
        "data_fields": [{"field": "Zone", "aggregation": "count", "show_data_as": "total_percentage"}],
    }


def contract_cases():
    valid = valid_args()
    cases = [("relative", valid, True)]
    for key in valid:
        cases.append(("missing_" + key, {k: v for k, v in valid.items() if k != key}, False))
    for gap in [-1, 0, 2, True, "1"]:
        cases.append((f"wrong_gap_{gap!r}", {**valid, "blank_rows": gap}, False))
    cases.extend([
        ("partial_only", {k: valid[k] for k in ["row_fields", "data_fields"]}, False),
        ("mixed_location", {**valid, "destination": "H8"}, False),
        ("title_zero_gap", {**valid, "below_range": "H1:I2", "blank_rows": 0}, True),
        ("other_observed", {**valid, "below_range": "H8:I11", "blank_rows": 2}, False),
        ("longer_reference", {**valid, "below_range": "H3:I60", "blank_rows": 0}, True),
        ("anchor_zero_gap", {**valid, "below_range": "$H$3:$I$6", "blank_rows": 0}, True),
        ("invalid_reference", {**valid, "below_range": "H0:I6"}, False),
        ("unexpected", {**valid, "extra": "value"}, False),
    ])
    absolute = {k: v for k, v in valid.items() if k not in {"below_range", "blank_rows"}}
    cases.append(("absolute", {**absolute, "destination": "H3"}, True))
    for key, value in [("field", "Ticket"), ("aggregation", "sum"), ("show_data_as", "row_percentage"),
                       ("extra", "unexpected")]:
        args = deepcopy(valid)
        args["data_fields"][0][key] = value
        cases.append(("wrong_measure_" + key, args, False))
    args = deepcopy(valid)
    args["row_fields"] = ["Status"]
    cases.append(("category_mismatch", args, False))
    args = deepcopy(valid)
    args["row_fields"] = ["Status"]
    args["data_fields"][0]["field"] = "Status"
    cases.append(("other_category", args, True))
    return cases


@pytest.mark.parametrize("label,args,expected", contract_cases(), ids=lambda v: v if isinstance(v, str) else None)
def test_wire_and_authoritative_contracts_agree(label, args, expected):
    tools = pivot_tools()
    original = deepcopy(tools)
    wire = _qwen_schema_compatible_tools("Qwen3.5-9B", tools)
    assert tools == original
    for schema in [tools[0]["function"]["parameters"], wire[0]["function"]["parameters"]]:
        assert Draft202012Validator(schema).is_valid(args) == expected, label
    for branch in wire[0]["function"]["parameters"]["oneOf"]:
        assert {"source_sheet", "source_range", "destination_sheet", "name", "data_fields"} <= set(branch["required"])
        assert "allOf" not in branch
        assert branch["additionalProperties"] is False
        assert branch["properties"]["data_fields"]["items"]["additionalProperties"] is False


def test_base_contract_preserves_legacy_and_both_placement_styles():
    tools = pivot_tools(False)
    wire = _qwen_schema_compatible_tools("Qwen3.5-9B", tools)
    args = valid_args()
    absolute = {k: v for k, v in args.items() if k not in {"below_range", "blank_rows"}}
    for value in [args, {**absolute, "destination": "H3"},
                  {**absolute, "destination": {"below_range": "H1:I2", "blank_rows": 0}}]:
        for source in [tools, wire]:
            Draft202012Validator(source[0]["function"]["parameters"]).validate(value)


@pytest.mark.parametrize("event_count", [1, 3, 8])
@pytest.mark.parametrize("relation", ["const", "minimum", "maximum"])
def test_progressive_observations_and_gap_bounds_remain_equivalent(event_count, relation):
    current = state()
    current.events = current.events[:event_count]
    tools = build_tools(current.domain, ["pivot.create"], include_gui=False, include_control_tools=False)
    function = tools[0]["function"]
    constrain_tool(function, current)
    constrain_layout(function, current)
    schema = function["parameters"]
    for clause in schema["allOf"][1:]:
        clause["then"]["properties"]["blank_rows"] = {"type": "integer", relation: 1}
    wire = _qwen_schema_compatible_tools("Qwen3.5-9B", tools)[0]["function"]["parameters"]
    for reference in ["H3:I6", "H8:I11", "H1:I2", "H3:I60"]:
        for gap in [0, 1, 2]:
            args = {**valid_args(), "below_range": reference, "blank_rows": gap}
            assert Draft202012Validator(schema).is_valid(args) == Draft202012Validator(wire).is_valid(args)


def test_nested_params_are_lowered_without_losing_wrapper_contract():
    nested = {"type": "object", "properties": {"params": pivot_tools()[0]["function"]["parameters"]},
              "required": ["params"], "additionalProperties": False}
    result = lower_pivot_schemas(nested)
    Draft202012Validator(result).validate({"params": valid_args()})
    assert not Draft202012Validator(result).is_valid({"params": {}})
    assert not Draft202012Validator(result).is_valid({"params": valid_args(), "extra": True})


@pytest.mark.parametrize("change", ["condition", "category", "root"])
def test_unknown_contract_fails_closed(change):
    tools = pivot_tools()
    schema = tools[0]["function"]["parameters"]
    if change == "condition":
        schema["allOf"].append({"if": {"required": ["name"]}, "then": {"required": ["replace"]}})
    elif change == "category":
        schema["oneOf"].append(deepcopy(schema["oneOf"][0]))
    else:
        schema["maxProperties"] = 7
    with pytest.raises(UnsupportedPivotSchema):
        _qwen_schema_compatible_tools("Qwen3.5-9B", tools)


def test_exact_range_complement_preserves_all_other_a1_references():
    excluded = ["A2", "A20", "A2:B5", "$A$2", "H3:I6", "not a range"]
    pattern = re.compile(_excluding_ranges(excluded))
    candidates = excluded + ["A1", "A21", "A200", "A2:B50", "$A$21", "a2", "H3:I60", "A0", "A1:", "AAAA1", "AAAAA1"]
    for candidate in candidates:
        assert bool(pattern.fullmatch(candidate)) == (bool(A1_RANGE_PATTERN.fullmatch(candidate)) and candidate not in excluded)


@pytest.mark.parametrize("stop", [None, QWEN_TOOL_CALL_END])
@pytest.mark.parametrize("label,args,valid", contract_cases(), ids=lambda v: v if isinstance(v, str) else None)
def test_request_lowering_keeps_local_validation_and_never_fills_arguments(stop, label, args, valid):
    tools = pivot_tools()
    tools.append({"type": "function", "function": {"name": "inspect", "parameters": {
        "type": "object", "properties": {}, "required": [], "additionalProperties": False}}})
    requests = []

    def create(**request):
        requests.append(request)
        return SimpleNamespace(model="Qwen3.5-9B", usage=None, choices=[SimpleNamespace(
            finish_reason="tool_calls", message=SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                id="1", function=SimpleNamespace(name="adapter__pivot_create", arguments=json.dumps(args)))]))])

    client = StructuredToolModelClient(base_url="http://unused", api_key="EMPTY", request_timeout_seconds=1,
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    kwargs = dict(model="Qwen3.5-9B", messages=[], tools=tools, temperature=0,
                  output_token_budget=1024, enable_thinking=True, tool_call_stop_sequence=stop)
    if not valid:
        with pytest.raises(StructuredToolProtocolError):
            client.propose(**kwargs)
    else:
        assert json.loads(client.propose(**kwargs)["arguments_raw"]) == args
    request = requests[0]
    wire = request["tools"][0]["function"]["parameters"]
    assert "allOf" not in wire
    assert "allOf" in tools[0]["function"]["parameters"]
    if stop:
        tag = json.loads(request["extra_body"]["structured_outputs"]["structural_tag"])["format"]["tags"][0]
        assert tag["content"]["json_schema"] == wire
        assert tag["content"]["any_order"] is False


def test_other_models_keep_public_schema():
    tools = pivot_tools()
    assert _qwen_schema_compatible_tools("other-model", tools) is tools


def test_actual_xgrammar_preserves_required_and_conditional_parameters():
    """Also runnable on the service host with its exact XGrammar build."""
    xgr = pytest.importorskip("xgrammar")
    schema = _qwen_schema_compatible_tools("Qwen3.5-9B", pivot_tools())[0]["function"]["parameters"]
    tag = {"type": "tag", "begin": "<tool_call>\n<function=adapter__pivot_create>\n",
           "content": {"type": "json_schema", "json_schema": schema, "style": "qwen_xml", "any_order": False},
           "end": QWEN_TOOL_CALL_END}
    compiler = xgr.GrammarCompiler(xgr.TokenizerInfo(
        [bytes([i]) for i in range(256)] + [b"<eos>"], stop_token_ids=[256]), max_threads=1)
    compiled = compiler.compile_grammar(xgr.Grammar.from_structural_tag({"type": "structural_tag", "format": tag}))

    def ordered(value, shape):
        if isinstance(value, dict):
            props = shape.get("properties", {})
            return {k: ordered(value[k], props.get(k, {}))
                    for k in [*props, *(k for k in value if k not in props)] if k in value}
        if isinstance(value, list):
            return [ordered(v, shape.get("items", {})) for v in value]
        return value

    for label, args, expected in contract_cases():
        if label == "mixed_location":
            # Native XML pattern strings can consume </parameter> delimiters.
            # That provider ambiguity is independently rejected by the full
            # client matrix above, using the original authoritative schema.
            continue
        parts = []
        for key, value in ordered(args, schema).items():
            raw = value if isinstance(value, str) and schema["properties"].get(key, {}).get("type") == "string" else json.dumps(value)
            parts.append(f"<parameter={key}>\n{raw}\n</parameter>")
        xml = tag["begin"] + "\n".join(parts) + tag["end"]
        matcher = xgr.GrammarMatcher(compiled)
        assert (matcher.accept_string(xml) and matcher.is_completed()) == expected, label
