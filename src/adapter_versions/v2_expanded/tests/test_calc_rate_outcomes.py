"""Rate units must follow native source representations, not labels alone."""
from copy import deepcopy

import pytest

from integrations.lite_agent.calc_rate_outcomes import outcome_issues, constrain_tool
from integrations.lite_agent.state_model import RuntimeState
from integrations.lite_agent.tool_catalog import build_tools
from test_completion_outcomes import event


def current(percent=False):
    values = [["Yearly Rate (%)", "Periods per year"], [0.12 if percent else 12, 4], [0.06 if percent else 6, 2]]
    source = {"display_text": [[str(c) for c in row] for row in values], "values": values,
              "kinds": [["string", "string"], ["number", "number"], ["number", "number"]],
              "number_formats": [[{"type": 16}, {"type": 16}],
                                 [{"type": 4 if percent else 16}, {"type": 16}],
                                 [{"type": 4 if percent else 16}, {"type": 16}]]}
    target = {"display_text": [["Periodic output (%)"], ["3"], ["3"]],
              "values": [["Periodic output (%)"], [3], [3]], "kinds": [["string"], ["formula"], ["number"]],
              "number_formats": [[{"type": 16}], [{"type": 16}], [{"type": 16}]]}
    return RuntimeState(task_id="synthetic-unit", domain="libreoffice_calc",
                        instruction='Calculate the period rate in a new column with header "Periodic output (%)" and highlight the highest result with green (#00ff00) font.',
                        events=[event(1, "workbook.inspect", result={"sheets": [{"name": "Rates", "used_range_a1": "D5:E7"}]}),
                                event(2, "range.read", {"sheet": "Rates", "range": "D5:E7"}, source),
                                event(3, "range.write", {"sheet": "Rates", "range": "F5:F7"}),
                                event(4, "workbook.save"),
                                event(5, "range.read", {"sheet": "Rates", "range": "F5:F7"}, target)])


@pytest.mark.parametrize("percent", [False, True])
def test_native_source_units_accept_equivalent_numeric_or_formula_results(percent):
    assert outcome_issues(current(percent)) == []


@pytest.mark.parametrize("value", [300, .03, "3", True])
def test_label_does_not_justify_extra_scaling_or_text_results(value):
    state = current()
    state.events[-1].result["context_hint"]["values"][1][0] = value
    issues = outcome_issues(state)
    assert issues[0]["code"] == "period_rate.unit_mismatch"
    assert issues[0]["observed"]["incorrect_cells"][0]["cell"] == "F6"


def test_preserves_input_rechecks_fresh_outputs_and_numeric_format():
    state = current()
    state.events.append(event(6, "range.write", {"sheet": "Rates", "range": "D6"}))
    assert outcome_issues(state)[0]["code"] == "period_rate.source_unverified"
    state = current()
    state.events[-1].result["context_hint"]["number_formats"][1][0]["type"] = 4
    assert outcome_issues(state)[0]["code"] == "period_rate.unit_mismatch"
    state = current()
    state.events.append(event(6, "workbook.save"))
    assert outcome_issues(state)[0]["code"] == "period_rate.output_unverified"


@pytest.mark.parametrize("change", ["compound", "ambiguous_header", "unknown_format", "source_edited", "other_document"])
def test_unsupported_or_uncertain_sources_do_not_invent_expected_rates(change):
    state = current()
    if change == "compound":
        state.instruction += " Use compound interest."
    elif change == "ambiguous_header":
        state.events[1].result["context_hint"]["display_text"][0][1] = "Yearly Rate (%)"
    elif change == "unknown_format":
        state.events[1].result["context_hint"].pop("number_formats")
    elif change == "source_edited":
        state.events.insert(1, event(1, "range.write", {"sheet": "Rates", "range": "D6"}))
    else:
        state.events.extend([event(6, "workbook.open", {"url": "file:///other.xlsx"}),
                             event(7, "workbook.inspect", result={"url": "file:///other.xlsx", "sheets": []})])
    assert outcome_issues(state) == []


def test_guidance_does_not_change_schema_or_select_a_formula_or_cell():
    state = current()
    tool = build_tools(state.domain, ["range.write"], include_gui=False, include_control_tools=False)[0]["function"]
    old = deepcopy(tool)
    constrain_tool(tool, state)
    assert tool["parameters"] == old["parameters"]
    assert "Observed rate-unit evidence" in tool["description"]
    assert "=D6/E6" not in tool["description"]
