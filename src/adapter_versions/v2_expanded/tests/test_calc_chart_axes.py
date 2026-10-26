"""Explicit axis identities are checked from live sources, not header flags."""
from copy import deepcopy

import pytest

from integrations.lite_agent.calc_chart_axes import axis_issues, _request
from integrations.lite_agent.calc_chart_outcomes import _observations
from integrations.lite_agent.completion_outcomes import _events
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState

INSTRUCTION = 'Create a line chart with "Cycle" on the X-axis and Pressure on the Y-axis.'


def chart():
    return {"name": "Trend", "type": "line", "source_sheet": "Lab Results", "column_headers": True,
            "source_ranges": ["C8:C11", "G8:G11"],
            "data_series": [{"labels": ["Pressure"], "source_ranges": ["$'Lab Results'.$G$9:$G$11"]}],
            "category_axes": [{"source_range": "$'Lab Results'.$C$9:$C$11", "labels": [1, 2, 3]}]}


def observations():
    return [("Lab Results", (3, 8, 7, 11), [["Cycle", "", "", "", "Pressure"],
             [1, "", "", "", 11], [2, "", "", "", 12], [3, "", "", "", 13]], 2)]


def check(c=None, obs=None, instruction=INSTRUCTION):
    return axis_issues(instruction, c or chart(), "Lab Results", observations() if obs is None else obs, 6)


def test_numeric_category_is_legal_independent_of_flags():
    assert check() == []
    c = chart()
    c["row_headers"] = False  # Native binding, not a flag, establishes the role.
    assert check(c) == []


def test_dates_are_legal_categories():
    c = chart()
    c["category_axes"][0]["labels"] = [45000, 45001, 45002]
    assert check(c) == []


def test_x_as_value_and_empty_native_categories_is_definite_mismatch():
    c = chart()
    c["category_axes"] = []
    c["data_series"].insert(0, {"labels": ["Cycle"], "source_ranges": ["$'Lab Results'.$C$9:$C$11"]})
    issues = check(c, obs=[])
    assert len(issues) == 1
    assert issues[0]["code"] == "charts.axis_roles_mismatch" and issues[0]["kind"] == "state_mismatch"
    assert issues[0]["expected"] == {"x_category_field": "cycle", "y_value_field": "pressure"}


def test_wrong_x_and_wrong_y_roles():
    c = chart()
    c["category_axes"][0]["source_range"] = "G9:G11"
    c["data_series"][0] = {"labels": ["Cycle"], "source_ranges": ["C9:C11"]}
    assert check(c)[0]["code"] == "charts.axis_roles_mismatch"


def test_additional_x_value_series_is_mismatch():
    c = chart()
    c["data_series"].append({"labels": ["Cycle"], "source_ranges": ["C9:C11"]})
    assert check(c)[0]["code"] == "charts.axis_roles_mismatch"


def test_multiple_series_of_the_same_field_are_legal():
    c = chart()
    c["data_series"].append(deepcopy(c["data_series"][0]))
    assert check(c) == []


def test_row_layout_and_alternate_names():
    c = chart()
    c.update(column_headers=True, row_headers=True, source_ranges=["D4:F4", "C9:F9"])
    c["category_axes"] = [{"source_range": "D4:F4"}]
    c["data_series"] = [{"labels": ["Velocity"], "source_ranges": ["D9:F9"]}]
    obs = [("Lab Results", (3, 4, 6, 9), [["Elapsed", 1, 2, 3], ["", "", "", ""],
            ["", "", "", ""], ["", "", "", ""], ["", "", "", ""], ["Velocity", 4, 5, 6]], 2)]
    c["source_ranges"] = ["C4:F4", "C9:F9"]
    assert check(c, obs, 'Create a line chart with Elapsed as X axis and Velocity as Y axis.') == []


@pytest.mark.parametrize("key", ["data_series_inspect_error", "data_series_omitted_from_context", "category_axes_omitted_from_context"])
def test_partial_native_evidence_is_unknown(key):
    c = chart()
    c[key] = 1
    assert check(c)[0]["kind"] == "missing_observation"


def test_unobserved_category_identity_requires_reading_headers():
    c = chart()
    c["data_series"].append({"labels": ["Cycle"], "source_ranges": ["C9:C11"]})
    c["category_axes"][0]["source_range"] = "K9:K11"
    assert check(c, obs=[])[0]["code"] == "charts.axis_roles_unverified"


def test_conflicting_header_and_native_label_are_unknown():
    c = chart()
    obs = observations()
    obs[0][2][0][4] = "Cycle"
    assert check(c, obs)[0]["kind"] == "missing_observation"


@pytest.mark.parametrize("instruction", [
    'Create two line charts with Cycle on X axis and Pressure on Y axis.',
    'Create a chart of Cycle and Pressure.',
    'Create a line chart with Cycle on X axis and Pressure and Temperature on Y axis.',
])
def test_ambiguous_instructions_do_not_gain_axis_contract(instruction):
    c = chart()
    c["data_series"].append({"labels": ["Temperature"], "source_ranges": ["K9:K11"]})
    assert check(c, instruction=instruction) == []


@pytest.mark.parametrize("kind", ["scatter", "pie", "bar"])
def test_other_chart_types_are_unchanged(kind):
    c = chart()
    c["type"] = kind
    c["category_axes"] = []
    assert check(c) == []


def test_multiple_coordinate_systems_are_unchanged():
    c = chart()
    c["data_series"][0]["coordinate_system"] = 1
    assert check(c) == []


def test_case_quotes_and_whitespace_normalization():
    assert _request('Make a line chart with “CYCLE” column on the x-axis and pressure on the y-axis.',
                    {"cycle", "pressure"}) == ("cycle", "pressure")


def test_stale_read_headers_are_not_reused_after_writes():
    def e(step, action, args, result):
        return ExecutionEvent(step=step,timestamp_utc="2031-01-01T00:00:00Z",
                              proposed={"kind":"adapter","action":action,"arguments":args},
                              parsed=True,validated=True,executed=True,result={"context_hint":result})
    s = RuntimeState(task_id="axis-freshness",domain="libreoffice_calc",instruction=INSTRUCTION,events=[
        e(1,"range.read",{"sheet":"Lab Results","range":"C8:G11"},{"values":observations()[0][2]}),
        e(2,"range.write",{"sheet":"Lab Results","range":"C8"},{})])
    assert _observations(_events(s)) == []
    c = chart()
    # With no live category identity the checker does not invent a binding.
    assert check(c, obs=_observations(_events(s)))[0]["code"] == "charts.axis_roles_unverified"


@pytest.mark.parametrize("fields", ["Pressure plus Temperature", "Pressure or Temperature", "Pressure & Temperature",
                                    "Pressure with Temperature", "Pressure, Temperature, and Humidity"])
def test_coordinated_multiple_y_fields_are_left_to_existing_review(fields):
    c = chart()
    c["data_series"].extend([{"labels": ["Temperature"], "source_ranges": ["K9:K11"]},
                             {"labels": ["Humidity"], "source_ranges": ["L9:L11"]}])
    assert check(c, instruction=f"Create a line chart with Cycle on X axis and {fields} on Y axis.") == []


@pytest.mark.parametrize("modifier", ["combo", "combination", "combined", "secondary axis", "right-axis", "dual axis"])
def test_explicit_mixed_or_multiple_axes_are_unchanged(modifier):
    assert check(instruction=INSTRUCTION + f" Use a {modifier} chart.") == []


@pytest.mark.parametrize("key", ["labels_omitted_from_context", "source_ranges_omitted_from_context", "inspect_error"])
def test_partial_series_identity_is_missing_observation(key):
    c = chart()
    c["data_series"][0][key] = 1
    assert check(c)[0]["code"] == "charts.axis_roles_unverified"
