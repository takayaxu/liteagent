"""Native spacing and repair evidence, including the two-blank-row regression."""
from copy import deepcopy
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from calc_adapter import uno_worker
from calc_adapter.errors import AdapterError
from calc_adapter.schema import validate_action_params
from integrations.lite_agent.calc_pivot_layout import constrain_tool, spacing_requirement
from integrations.lite_agent.completion_outcomes import completion_outcome_issues, outcome_retry_allowed
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools
from test_calc_percentage_outcomes import state
from test_calc_pivot_output_contract import _native_pivot_fixture, _pivot_params
from test_completion_outcomes import agent, claim, event, state as sum_state


def with_gap(gap=2, phrase="a blank line"):
    current = state()
    current.instruction = current.instruction.replace("a blank line", phrase)
    pivot = current.events[6].result["context_hint"]["sheets"][1]["pivot_tables"][1]
    pivot["output_range"] = f"H{7 + gap}:I{10 + gap}"
    read = current.events[-1]
    read.proposed["arguments"]["range"] = f"H3:I{10 + gap}"
    payload = read.result["context_hint"]
    for field, blank in [("display_text", ""), ("values", None), ("kinds", "blank")]:
        rows = payload[field]
        payload[field] = rows[:4] + [[blank, blank] for _ in range(gap)] + rows[-4:]
    return current


@pytest.mark.parametrize("phrase,expected,relation", [
    ("a blank line", 1, "exact"), ("one blank row", 1, "exact"),
    ("two blank lines", 2, "exact"), ("3 blank rows", 3, "exact"),
    ("no blank rows", 0, "exact"), ("at least two blank rows", 2, "minimum"),
    ("at most three blank lines", 3, "maximum"), ("blank rows", 1, "minimum"),
])
def test_spacing_cardinality_preserves_explicit_qualifiers(phrase, expected, relation):
    assert spacing_requirement("Stack the pivots with " + phrase + " between them.") == {
        "blank_rows": expected, "relation": relation,
    }
    assert spacing_requirement("Put charts side by side with " + phrase + ".") is None


def test_title_spacing_does_not_override_the_table_separator_count():
    assert spacing_requirement("Leave one blank line below the title. Stack the pivots with two blank rows between them.") == {
        "blank_rows": 2, "relation": "exact",
    }
    assert spacing_requirement("Stack the tables. Leave one blank line after the title.") == {
        "blank_rows": 0, "relation": "minimum",
    }


@pytest.mark.parametrize("gap,phrase,valid", [
    (0, "a blank line", False), (1, "a blank line", True), (2, "a blank line", False),
    (1, "two blank rows", False), (2, "two blank rows", True), (3, "two blank rows", False),
    (0, "no blank rows", True), (2, "at least one blank row", True),
    (2, "at most two blank rows", True), (3, "at most two blank rows", False),
])
def test_gate_counts_actual_separator_rows(gap, phrase, valid):
    issues = completion_outcome_issues(with_gap(gap, phrase))
    assert (not issues) is valid, issues
    if not valid:
        issue = next(i for i in issues if i["code"] == "pivot.layout_mismatch")
        assert issue["target"]["name"] == "ByStatus"
        assert issue["expected"]["blank_rows"] == spacing_requirement(with_gap(gap, phrase).instruction)["blank_rows"]
        assert issue["observed"]["blank_rows"] == gap


def test_two_rows_are_rejected_before_source_evidence_or_model_self_review():
    current = with_gap()
    current.events.pop(1)
    issues = completion_outcome_issues(current)
    assert {"pivot.layout_mismatch", "pivot.source_unverified"} <= {i["code"] for i in issues}
    worker = agent()
    assert not claim(worker, current).executed
    tools = {t["function"]["name"] for t in worker.tools(current)}
    assert {"adapter__pivot_create", "adapter__range_read", "adapter__workbook_save", "tools_search"} <= tools
    issue = next(i for i in issues if i["code"] == "pivot.layout_mismatch")
    assert issue["expected"]["destination"] == "H8"
    assert issue["expected"]["below_range"] == "H3:I6"


def test_spacing_contract_applies_to_sum_pivots_too():
    current = sum_state()
    current.instruction += " Stack the tables, separated by a blank line."
    # Sum fixture has two blank rows between H3:I6 and H9:I12.
    assert "pivot.layout_mismatch" in {i["code"] for i in completion_outcome_issues(current)}


def test_layout_does_not_depend_on_recognizing_the_measure_or_percentage_clause():
    current = with_gap()
    current.instruction = 'Create two pivot tables in a new sheet named "Summary". Stack them with one blank row between them.'
    assert "pivot.layout_mismatch" in {i["code"] for i in completion_outcome_issues(current)}


def test_corrected_inventory_alone_does_not_clear_required_cell_evidence():
    current = with_gap()
    worker = agent()
    assert not claim(worker, current).executed
    corrected = state()
    args = {"name": "ByStatus", "destination_sheet": "Summary", "replace": True,
            "below_range": "H3:I6", "blank_rows": 1}
    assert outcome_retry_allowed(current, current.domain, "pivot.create", args, 5)
    args["blank_rows"] = 2
    assert not outcome_retry_allowed(current, current.domain, "pivot.create", args, 5)
    args["blank_rows"] = 1
    current.events += [event(10, "pivot.create", args), event(11, "workbook.save")]
    inspected = deepcopy(corrected.events[6])
    inspected.step = 12
    current.events.append(inspected)
    assert "pivot.gap_unverified" in {i["code"] for i in completion_outcome_issues(current)}
    assert "adapter__pivot_create" in {t["function"]["name"] for t in worker.tools(current)}
    read = deepcopy(corrected.events[-1])
    read.step = 13
    current.events.append(read)
    assert completion_outcome_issues(current) == []
    assert claim(worker, current).executed


@pytest.mark.parametrize("gap", [0, 1, 3])
@pytest.mark.parametrize("wrapped", [False, True])
def test_flat_relative_placement_preserves_explicit_model_arguments(gap, wrapped):
    args = _pivot_params()
    args.pop("destination")
    args.update(below_range="H2:J3", blank_rows=gap)
    original = deepcopy(args)
    if wrapped:
        tools = constrain_adapter_call_routes(
            build_tools("multi_apps", ["adapter.call"], include_gui=False, strict_generic=True),
            [("libreoffice_calc", "pivot.create")],
        )
        schema = next(t["function"] for t in tools if t["function"]["name"] == "adapter__adapter_call")["parameters"]
        Draft202012Validator(schema).validate({"adapter": "libreoffice_calc", "action": "pivot.create", "payload": {"params": args}})
    else:
        tool = build_tools("libreoffice_calc", ["pivot.create"], include_gui=False, include_control_tools=False)[0]
        Draft202012Validator(tool["function"]["parameters"]).validate(args)
    validate_action_params("pivot.create", args)
    assert args == original


@pytest.mark.parametrize("bad", [
    {"below_range": "H3:I6"}, {"blank_rows": 1},
    {"below_range": "H3:I6", "blank_rows": -1},
    {"below_range": "H3:I6", "blank_rows": True},
    {"below_range": "H3:I6", "blank_rows": "1"},
    {"below_range": "bad range", "blank_rows": 1},
    {"below_range": "H3:I6", "blank_rows": 1, "destination": "H8"},
])
def test_invalid_or_ambiguous_placement_is_rejected_without_coercion(bad):
    args = _pivot_params()
    args.pop("destination")
    args.update(bad)
    before = deepcopy(args)
    schema = build_tools("libreoffice_calc", ["pivot.create"], include_gui=False, include_control_tools=False)[0]["function"]["parameters"]
    assert list(Draft202012Validator(schema).iter_errors(args))
    with pytest.raises(AdapterError):
        validate_action_params("pivot.create", args)
    assert args == before


@pytest.mark.parametrize("gap,anchor", [(0, "H4"), (1, "H5"), (3, "H7")])
def test_native_worker_does_not_add_a_header_margin(monkeypatch, gap, anchor):
    output = SimpleNamespace(StartColumn=7, StartRow=int(anchor[1:]) - 1, EndColumn=9, EndRow=17)
    fixture = _native_pivot_fixture(monkeypatch, output, anchor=anchor)
    args = _pivot_params()
    args.pop("destination")
    args.update(below_range="H2:J3", blank_rows=gap)
    original = deepcopy(args)
    result = uno_worker._pivot_create(fixture.session, args)
    assert result["destination"] == anchor
    assert result["requested_destination"] == {"below_range": "H2:J3", "blank_rows": gap}
    assert args == original


def test_stacked_model_surface_uses_scalar_fields_and_keeps_valid_absolute_positions():
    current = state()
    tool = build_tools("libreoffice_calc", ["pivot.create"], include_gui=False, include_control_tools=False)[0]["function"]
    constrain_tool(tool, current)
    schema = tool["parameters"]
    assert schema["properties"]["destination"]["type"] == "string"
    assert schema["properties"]["below_range"]["type"] == "string"
    assert schema["properties"]["blank_rows"]["type"] == "integer"
    args = {"source_sheet": "Input", "source_range": "C4:E8", "destination_sheet": "Summary",
            "below_range": "H3:I6", "blank_rows": 1, "name": "ByStatus", "row_fields": ["Status"],
            "data_fields": [{"field": "Status", "aggregation": "count", "show_data_as": "total_percentage"}]}
    Draft202012Validator(schema).validate(args)
    args["blank_rows"] = 2
    assert list(Draft202012Validator(schema).iter_errors(args))
    args.pop("below_range")
    args.pop("blank_rows")
    args["destination"] = "H8"
    Draft202012Validator(schema).validate(args)
    args["destination"] = '{"below_range":"H3:I6","blank_rows":1}'
    assert list(Draft202012Validator(schema).iter_errors(args))


def test_recovery_surface_uses_flat_placement_without_shrinking_repair_tools():
    current = with_gap()
    tools = {t["function"]["name"]: t["function"] for t in agent().tools(current)}
    schema = tools["adapter__pivot_create"]["parameters"]
    assert schema["properties"]["destination"]["type"] == "string"
    assert schema["properties"]["below_range"]["type"] == "string"
    assert "adapter__range_read" in tools and "adapter__workbook_save" in tools


def test_title_to_first_table_gap_is_independent_of_inter_table_gap():
    current = state()
    tool = build_tools("libreoffice_calc", ["pivot.create"], include_gui=False, include_control_tools=False)[0]["function"]
    constrain_tool(tool, current)
    args = {"source_sheet": "Input", "source_range": "C4:E8", "destination_sheet": "Summary",
            "below_range": "H1:I2", "blank_rows": 0, "name": "ByZone", "row_fields": ["Zone"],
            "data_fields": [{"field": "Zone", "aggregation": "count", "show_data_as": "total_percentage"}]}
    Draft202012Validator(tool["parameters"]).validate(args)
