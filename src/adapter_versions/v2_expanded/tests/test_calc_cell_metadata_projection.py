from copy import deepcopy
from types import SimpleNamespace

import pytest

from integrations.lite_agent.adapter_results import (
    adapter_context_hint,
    execution_context_summary,
)
from integrations.lite_agent.context_projection import compact_execution_summary_for_model


def test_native_dates_and_backgrounds_reach_the_real_execution_context():
    observed = {
        "sheet": "Measurements",
        "range": "D8:E9",
        "display_text": [["10/04/2032", "label"], ["", "11/04/2032"]],
        "cell_addresses": [["D8", "E8"], ["D9", "E9"]],
        "date_cells": {
            "D8": {"date": "2032-04-10", "weekday": "Saturday"},
            "E9": {"date": "2032-04-11", "weekday": "Sunday"},
        },
        "background_cells": {"E8": "#335577", "D9": "#112233"},
    }
    original = deepcopy(observed)
    hint = adapter_context_hint("libreoffice_calc", "range.read", {"result": observed})
    event = SimpleNamespace(
        step=1,
        proposed={
            "kind": "adapter",
            "action": "range.read",
            "tool": "adapter__range_read",
            "arguments": {"sheet": "Measurements", "range": "D8:E9"},
        },
        result={"context_hint": hint, "adapter_response": {"result": observed}},
        executed=True,
        error=None,
    )
    visible = execution_context_summary([event], "libreoffice_calc", strict_generic=True)
    projected = visible[0]["result"]["context_hint"]
    assert projected["date_cells"] == original["date_cells"]
    assert projected["background_cells"] == original["background_cells"]
    assert projected["date_weekday_summary"] == hint["date_weekday_summary"]
    assert projected["display_text"] == original["display_text"]
    assert observed == original


@pytest.mark.parametrize("max_chars", [1600, 2600])
def test_bounded_read_keeps_addressed_metadata_before_large_text(max_chars):
    hint = adapter_context_hint(
        "libreoffice_calc",
        "range.read",
        {
            "result": {
                "sheet": "Measurements",
                "range": "B3:C6",
                "display_text": [["x" * 500, "y" * 500] for _ in range(4)],
                "date_cells": {"B3": {"date": "2032-04-10", "weekday": "Saturday"}},
                "background_cells": {"C6": "#112233"},
            }
        },
    )
    visible = compact_execution_summary_for_model(
        [{"step": 1, "action": "range.read", "executed": True, "result": {"context_hint": hint}}],
        max_chars=max_chars,
    )[0]["result"]["context_hint"]
    assert visible["context_truncated"] is True
    assert visible["date_cells"] == hint["date_cells"]
    assert visible["background_cells"] == hint["background_cells"]


def test_complete_white_background_read_is_distinct_from_missing_metadata():
    body = {"result": {"sheet": "Measurements", "range": "D8", "display_text": [[""]]}}
    missing = adapter_context_hint("libreoffice_calc", "range.read", body)
    assert "background_cells" not in missing
    body["result"]["background_cells"] = {}
    complete = adapter_context_hint("libreoffice_calc", "range.read", body)
    assert complete["background_cells"] == {}
    assert "white only when that map is complete" in complete["guidance"]


def test_weekday_summary_orders_all_dates_and_exposes_background_differences():
    observed = {
        "sheet": "Measurements",
        "range": "Z2:AA12",
        "date_cells": {
            "Z12": {"weekday": "Wednesday"},
            "AA2": {"weekday": "Wednesday"},
            "Z2": {"weekday": "Wednesday"},
            "Z3": {"weekday": "Thursday"},
        },
        "background_cells": {"Z12": "#335577", "AA2": "#335577"},
    }
    original = deepcopy(observed)
    hint = adapter_context_hint("libreoffice_calc", "range.read", {"result": observed})
    summary = hint["date_weekday_summary"]
    assert summary["date_cells_complete"] is True
    assert summary["background_cells_complete"] is True
    assert summary["weekdays"]["Wednesday"] == {
        "count": 3,
        "addresses": ["Z2", "Z12", "AA2"],
        "by_background": {"#ffffff": ["Z2"], "#335577": ["Z12", "AA2"]},
    }
    assert summary["weekdays"]["Thursday"]["addresses"] == ["Z3"]
    assert observed == original


@pytest.mark.parametrize("coverage", [
    {},
    {"background_cells": {}, "background_cells_truncated": True},
    {"background_cells": {}, "truncated": True, "date_cells_truncated": True},
])
def test_incomplete_backgrounds_never_become_white_in_weekday_summary(coverage):
    observed = {
        "sheet": "Measurements",
        "range": "H9:H10",
        "date_cells": {"H9": {"weekday": "Monday"}},
        **coverage,
    }
    hint = adapter_context_hint("libreoffice_calc", "range.read", {"result": observed})
    summary = hint["date_weekday_summary"]
    assert summary["background_cells_complete"] is False
    assert summary["weekdays"]["Monday"]["by_background"] == {"unknown": ["H9"]}
    assert summary["date_cells_complete"] is not bool(coverage.get("date_cells_truncated"))
    if coverage.get("truncated"):
        assert hint["truncated"] is True


def test_retry_projection_keeps_weekday_summary_before_large_cell_matrices():
    hint = adapter_context_hint("libreoffice_calc", "range.read", {"result": {
        "sheet": "Measurements",
        "range": "H9:I12",
        "display_text": [["x" * 500, "y" * 500] for _ in range(4)],
        "date_cells": {
            "H9": {"weekday": "Monday"}, "I12": {"weekday": "Monday"},
        },
        "background_cells": {"I12": "#335577"},
    }})
    visible = compact_execution_summary_for_model([
        {"step": 1, "action": "range.read", "executed": True, "result": {"context_hint": hint}}
    ], max_chars=1800)[0]["result"]["context_hint"]
    assert visible["context_truncated"] is True
    assert visible["date_weekday_summary"] == hint["date_weekday_summary"]


def test_conditional_formatting_guidance_requires_complete_target_coverage():
    hint = adapter_context_hint(
        "libreoffice_calc",
        "range.read",
        {
            "result": {
                "sheet": "Calendar",
                "range": "B3:F33",
                "display_text": [["date"]],
                "date_cells": {"B3": {"date": "2032-04-10", "weekday": "Saturday"}},
                "background_cells": {},
            }
        },
    )

    guidance = hint["guidance"]
    assert "every relevant populated row shown by workbook.inspect" in guidance
    assert "enumerate all matching A1 addresses" in guidance
    assert "check every expected address against background_cells" in guidance
    assert "successful format action does not prove" in guidance
