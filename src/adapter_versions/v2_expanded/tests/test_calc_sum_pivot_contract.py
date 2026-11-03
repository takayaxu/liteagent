"""Source-derived sum contracts agree in generation and local validation."""
from copy import deepcopy

from jsonschema import Draft202012Validator
import pytest

from integrations.lite_agent.calc_sum_pivot_contract import constrain_tool
from integrations.lite_agent.model_client import _qwen_schema_compatible_tools
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools
from test_completion_outcomes import agent, state as fixture_state


def state():
    current = fixture_state()
    current.events[0].result["context_hint"]["sheets"][0]["used_range_a1"] = "C4:E7"
    return current


def tool(current, wrapped=False):
    if wrapped:
        tools = constrain_adapter_call_routes(
            build_tools("multi_apps", ["adapter.call"], include_gui=False, strict_generic=True),
            [("libreoffice_calc", "pivot.create")],
        )
        function = next(t["function"] for t in tools if t["function"]["name"] == "adapter__adapter_call")
    else:
        function = build_tools("libreoffice_calc", ["pivot.create"], include_gui=False,
                               include_control_tools=False)[0]["function"]
    constrain_tool(function, current)
    return {"type": "function", "function": function}


def args(group="Region"):
    return {"source_sheet": "Input", "source_range": "C4:E7", "destination_sheet": "Summary",
            "name": "ModelChosenName", "destination": "L30", "row_fields": [group],
            "data_fields": [{"field": "Amount ($)", "aggregation": "sum"}]}


@pytest.mark.parametrize("wrapped", [False, True])
def test_generation_and_validation_preserve_placement_and_model_choice(wrapped):
    current = state()
    current.events = current.events[:3]
    original = deepcopy(current.events)
    selected = tool(current, wrapped)
    provider = _qwen_schema_compatible_tools("Qwen3.5-9B", [selected])[0]
    for group in ["Region", "Department"]:
        for relative in [False, True]:
            valid = args(group)
            if relative:
                valid.pop("destination")
                valid.update(below_range="L30:M40", blank_rows=3)
            cases = [(valid, True), ({**valid, "row_fields": ["Region", "Department"]}, False),
                     ({**valid, "row_fields": ["Unknown"]}, False),
                     ({**valid, "column_fields": ["Department"]}, False),
                     ({**valid, "destination": {"below_range": "L30:M40", "blank_rows": 1}}, False),
                     ({**valid, "destination": '{"below_range": "L30:M40", "blank_rows": 1}'}, False),
                     ({**valid, "page_fields": ["Region"]}, False),
                     ({**valid, "data_fields": [{"field": "Amount ($)", "aggregation": "count"}]}, False),
                     ({**valid, "data_fields": [{"field": "Region"}]}, False),
                     ({**valid, "data_fields": [{"field": "Amount ($)", "show_data_as": "row_percentage"}]}, False),
                     ({k: v for k, v in valid.items() if k != "source_range"}, False)]
            for value, expected in cases:
                if wrapped:
                    value = {"adapter": "libreoffice_calc", "action": "pivot.create", "payload": {"params": value}}
                for surface in [selected, provider]:
                    assert Draft202012Validator(surface["function"]["parameters"]).is_valid(value) is expected, value
    assert current.events == original


@pytest.mark.parametrize("instruction", [
    "Create two pivot tables for a cross-tab of region against department.",
    "Create two pivot tables showing the total amount for each region and department combination.",
    "Create two charts showing the total amount for each region and department.",
])
def test_unsupported_instructions_unchanged(instruction):
    current = state()
    current.instruction = instruction
    selected = build_tools(current.domain, ["pivot.create"], include_gui=False,
                           include_control_tools=False)[0]["function"]
    before = deepcopy(selected)
    constrain_tool(selected, current)
    assert selected == before


def test_missing_or_ambiguous_source_does_not_constrain():
    for source in [None, ["Region", "Region", "Amount ($)"]]:
        current = state()
        if source is None:
            current.events = current.events[:1]
        else:
            current.events[1].result["context_hint"]["display_text"][0] = source
        selected = build_tools(current.domain, ["pivot.create"], include_gui=False,
                               include_control_tools=False)[0]["function"]
        before = deepcopy(selected)
        constrain_tool(selected, current)
        assert selected == before


def test_normal_and_outcome_recovery_surfaces_publish_same_contract():
    current = state()
    for end in [3, 7]:
        current.events = state().events[:end]
        tools = agent().tools(current)
        selected = next(t for t in tools if t["function"]["name"] == "adapter__pivot_create")
        schema = selected["function"]["parameters"]
        assert Draft202012Validator(schema).is_valid(args())
        assert not Draft202012Validator(schema).is_valid({**args(), "column_fields": ["Department"]})
