"""Calculated values require source-bound formulas and fresh native results."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.calc_formula_contract import (
    argument_errors,
    outcome_issues,
)
from integrations.lite_agent.completion import CompletionMixin
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.tool_catalog import build_tools

INSTRUCTION = (
    'In a new sheet ("Changes") with 3 headers "Year", "Cash change", and '
    '"Equipment change", calculate the percentage annual changes compared '
    "to last year in 2019 to 2021 for the Cash, and Equipment columns."
)


def event(step, action, args=None, payload=None, executed=True):
    return ExecutionEvent(
        step=step,
        timestamp_utc="2030-01-01T00:00:00Z",
        proposed={"kind": "adapter", "action": action, "arguments": args or {}},
        parsed=True,
        validated=True,
        executed=executed,
        result={"context_hint": payload or {}},
        error=None if executed else {"type": "Failed"},
    )


def cells(sheet, area, values, formulas=None, kinds=None):
    return {
        "sheet": sheet,
        "range": area,
        "values": values,
        "display_text": [[str(v) for v in row] for row in values],
        "formulas": formulas or [[""] * len(row) for row in values],
        "kinds": kinds
        or [
            ["string" if isinstance(v, str) else "number" for v in row]
            for row in values
        ],
    }


def source_state():
    # Source and destination have independent offsets; source columns are reordered.
    source = [
        ["Equipment", "Year", "Cash"],
        [40, 2018, 100],
        [20, 2019, 125],
        [25, 2020, 100],
        [50, 2021, 110],
    ]
    return RuntimeState(
        task_id="synthetic-source-formulas",
        domain="libreoffice_calc",
        instruction=INSTRUCTION,
        events=[
            event(
                1,
                "workbook.inspect",
                payload={
                    "active_sheet": "Source data",
                    "sheets": [{"name": "Source data", "used_range_a1": "C4:F8"}],
                },
            ),
            event(2, "sheet.create", {"name": "Changes", "index": 1}),
            event(
                3,
                "range.read",
                {"sheet": "Source data", "range": "D4:F8"},
                cells("Source data", "D4:F8", source),
            ),
        ],
    )


def write_args(form="typed"):
    data = [["Year", "Cash change", "Equipment change"]]
    for year, source_row in zip(range(2019, 2022), range(6, 9)):
        row = [year]
        for col in ("F", "D"):
            expression = f"=('Source data'.{col}{source_row}-'Source data'.{col}{source_row - 1})/'Source data'.{col}{source_row - 1}"
            row.append(
                {"kind": "formula", "value": expression} if form == "typed" else 0.3169
            )
        data.append(row)
    return {"sheet": "Changes", "range": "H10:J13", "values": data}


def completed_state():
    state = source_state()
    args = write_args()
    state.events.append(event(4, "range.write", args))
    state.events.append(event(5, "workbook.save"))
    values = [
        ["Year", "Cash change", "Equipment change"],
        [2019, 0.25, -0.5],
        [2020, -0.2, 0.25],
        [2021, 0.1, 1.0],
    ]
    formulas = [["", "", ""]] + [
        ["", *[c["value"] for c in row[1:]]] for row in args["values"][1:]
    ]
    kinds = [["string"] * 3] + [["number", "formula", "formula"] for _ in range(3)]
    state.events.append(
        event(
            6,
            "range.read",
            {"sheet": "Changes", "range": "H10:J13"},
            cells("Changes", "H10:J13", values, formulas, kinds),
        )
    )
    display = state.events[-1].result["context_hint"]["display_text"]
    for row, native in zip(display[1:], values[1:]):
        row[1:] = [f"{v * 100:.2f}%" for v in native[1:]]
    return state


def test_calculation_is_bound_to_native_labels_coordinates_and_values():
    state = source_state()
    assert argument_errors(state, "range.write", write_args()) == []
    final = completed_state()
    assert outcome_issues(final) == []
    assert CompletionMixin._generic_completion_gate(final)["passed"]


@pytest.mark.parametrize(
    "literal", [0.3169, 31.69, "31.69", {"kind": "number", "value": 31.69}]
)
def test_precomputed_literals_blocked_before_dispatch_but_labels_allowed(literal):
    state = source_state()
    args = write_args()
    args["values"][1][1] = literal
    errors = argument_errors(state, "range.write", args)
    assert errors and "precomputed literal" in " ".join(errors)
    args["values"] = [
        ["Year", "Cash change", "Equipment change"],
        [2019, None, None],
        [2020, None, None],
        [2021, None, None],
    ]
    assert argument_errors(state, "range.write", args) == []


@pytest.mark.parametrize(
    "formula",
    [
        "=.3169",
        "=I11",
        "='Source data'.F5/'Source data'.F4-1",
        "='Source data'.D6/'Source data'.D5-1",
        "='Other'.F6/'Other'.F5-1",
        '=INDIRECT("Source data.F6")/INDIRECT("Source data.F5")-1',
    ],
)
def test_constant_wrong_column_year_sheet_and_self_references_are_rejected(formula):
    args = write_args()
    args["values"][1][1]["value"] = formula
    assert argument_errors(source_state(), "range.write", args)


def test_native_formula_result_must_match_the_operation_not_only_reference_tokens():
    state = completed_state()
    p = state.events[-1].result["context_hint"]
    p["formulas"][1][1] = "='Source data'.F6+'Source data'.F5"
    p["values"][1][1] = 225
    assert outcome_issues(state)[0]["code"] == "calculation.output_mismatch"
    assert not CompletionMixin._generic_completion_gate(state)["passed"]


@pytest.mark.parametrize(
    "defect",
    [
        "wrong_value",
        "constant_formula",
        "literal",
        "missing_formula",
        "nan",
        "error",
        "old_read",
        "truncated",
        "wrong_range",
        "save_before_change",
        "changed_source",
    ],
)
def test_completion_rejects_native_calculation_defects_or_stale_evidence(defect):
    state = completed_state()
    payload = state.events[-1].result["context_hint"]
    if defect == "wrong_value":
        payload["values"][1][1] = 0.3169
    elif defect == "constant_formula":
        payload["formulas"][1][1] = "=.25"
    elif defect == "literal":
        payload["kinds"][1][1] = "number"
    elif defect == "missing_formula":
        payload["formulas"][1][1] = ""
    elif defect == "nan":
        payload["values"][1][1] = float("nan")
    elif defect == "error":
        payload["values"][1][1] = "Err:522"
    elif defect == "old_read":
        state.events.append(
            event(
                7,
                "range.format",
                {
                    "sheet": "Changes",
                    "range": "I11:J13",
                    "format": {"number_format": "0.00%"},
                },
            )
        )
    elif defect == "truncated":
        payload["context_truncated"] = True
    elif defect == "wrong_range":
        payload["range"] = "H9:J12"
    elif defect == "save_before_change":
        state.events = state.events[:4] + state.events[5:]
    elif defect == "changed_source":
        state.events.append(
            event(
                7,
                "range.write",
                {"sheet": "Source data", "range": "F5", "values": [[999]]},
            )
        )
    assert outcome_issues(state), defect
    assert not CompletionMixin._generic_completion_gate(state)["passed"]


def test_split_source_windows_and_formula_writes_have_the_same_contract():
    state = source_state()
    source = state.events.pop()
    full = source.result["context_hint"]["values"]
    for index, col in enumerate(("D", "E", "F")):
        state.events.append(
            event(
                len(state.events) + 1,
                "range.read",
                {"sheet": "Source data", "range": f"{col}4:{col}8"},
                cells("Source data", f"{col}4:{col}8", [[row[index]] for row in full]),
            )
        )
    args = write_args()
    labels = deepcopy(args)
    for row in labels["values"][1:]:
        row[1:] = [None, None]
    state.events.append(event(6, "range.write", labels))
    writes = [
        {"cell": f"{col}{row}", "formula": args["values"][row - 10][index]["value"]}
        for row in range(11, 14)
        for index, col in ((1, "I"), (2, "J"))
    ]
    assert (
        argument_errors(
            state, "cells.set_formulas", {"sheet": "Changes", "writes": writes}
        )
        == []
    )
    assert argument_errors(
        state,
        "cells.set_formulas",
        {"sheet": "Changes", "writes": [{"cell": "I11", "formula": "=.3169"}]},
    )


def test_zero_denominator_or_ambiguous_sources_cannot_be_claimed_correct():
    state = completed_state()
    state.events[2].result["context_hint"]["values"][1][2] = 0
    assert outcome_issues(state)[0]["code"] == "calculation.source_undefined"
    state = completed_state()
    second = deepcopy(state.events[2])
    second.proposed["arguments"]["sheet"] = "Another input"
    second.result["context_hint"]["sheet"] = "Another input"
    state.events.insert(3, second)
    assert outcome_issues(state)[0]["code"] == "calculation.source_unverified"


def test_unrelated_tasks_and_sheets_retain_literal_writes():
    state = source_state()
    assert (
        argument_errors(
            state,
            "range.write",
            {"sheet": "Raw input", "range": "A1", "values": [[31.69]]},
        )
        == []
    )
    state.instruction = "Write the supplied number 31.69 to Changes!A1."
    assert (
        argument_errors(
            state,
            "range.write",
            {"sheet": "Changes", "range": "A1", "values": [[31.69]]},
        )
        == []
    )
    assert outcome_issues(state) == []


def test_execution_blocks_bad_arithmetic_without_changing_model_arguments():
    class Capture:
        def __init__(self):
            self.calls = []

        def execute(self, domain, action, args, metadata):
            self.calls.append(deepcopy(args))
            return {"executed": True, "result": {}}

    state = source_state()
    executor = Capture()
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused/v1", include_gui=False),
        executor,
        model_client=SimpleNamespace(client=object()),
    )
    tools = build_tools(state.domain, ["range.write"], include_gui=False)
    wrong = write_args("literal")
    result = agent.execute_proposal(
        state,
        {
            "tool": "adapter__range_write",
            "arguments_raw": json.dumps(wrong),
            "_model_visible_tools": tools,
        },
    )
    assert not result.executed and not executor.calls
    assert "precomputed literal" in result.error["detail"]
    right = write_args()
    result = agent.execute_proposal(
        state,
        {
            "tool": "adapter__range_write",
            "arguments_raw": json.dumps(right),
            "_model_visible_tools": tools,
        },
    )
    assert result.executed, result.error
    assert executor.calls == [right]
    assert result.proposed.get("arguments_source") is None
    visible = agent.tools(state)
    names = {t["function"]["name"] for t in visible}
    assert {
        "adapter__range_read",
        "adapter__range_write",
        "adapter__cells_set_formulas",
    } <= names
    assert any(
        "model-authored Calc formulas" in t["function"]["description"] for t in visible
    )


def test_separately_written_formulas_can_complete_from_native_final_read():
    state = completed_state()
    args = state.events[3].proposed["arguments"]
    labels = deepcopy(args)
    for row in labels["values"][1:]:
        row[1:] = [None, None]
    state.events[3].proposed["arguments"] = labels
    writes = [
        {"cell": f"{col}{row}", "formula": args["values"][row - 10][index]["value"]}
        for row in range(11, 14)
        for index, col in ((1, "I"), (2, "J"))
    ]
    state.events.insert(
        4, event(5, "cells.set_formulas", {"sheet": "Changes", "writes": writes})
    )
    for index, e in enumerate(state.events, 1):
        e.step = index
    assert outcome_issues(state) == []
    # Formula writes are valid calculations too; range.write remains necessary
    # for labels, but there is no obligation to use both formula-writing APIs.
    assert CompletionMixin._generic_completion_gate(state)["passed"]


def test_final_read_must_refresh_year_labels_and_source_document_identity():
    state = completed_state()
    payload = state.events[-1].result["context_hint"]
    state.events[-1].proposed["arguments"]["range"] = "I11:J13"
    payload["range"] = "I11:J13"
    for key in ("values", "display_text", "formulas", "kinds"):
        payload[key] = [row[1:] for row in payload[key][1:]]
    assert outcome_issues(state)[0]["code"] == "calculation.final_readback_missing"
    state = completed_state()
    state.events[0].result["context_hint"]["url"] = "file:///tmp/current.xlsx"
    state.events[2].result["context_hint"]["workbook_url"] = (
        "file:///tmp/unrelated.xlsx"
    )
    assert outcome_issues(state)[0]["code"] == "calculation.source_unverified"


def test_whole_workbook_open_and_duplicate_years_do_not_reuse_old_source():
    state = completed_state()
    state.events.append(event(7, "workbook.open", {"path": "/tmp/different.xlsx"}))
    assert outcome_issues(state)[0]["code"] == "calculation.source_unverified"
    state = completed_state()
    state.events[2].result["context_hint"]["values"][2][1] = 2018
    assert outcome_issues(state)[0]["code"] == "calculation.source_unverified"


def test_native_percent_display_can_be_inline_without_a_format_call():
    state = completed_state()
    assert outcome_issues(state) == []
    payload = state.events[-1].result["context_hint"]
    payload["display_text"][1][1] = "0.25"
    assert outcome_issues(state)[0]["code"] == "calculation.display_unverified"
    state = completed_state()
    state.events[-1].result["context_hint"]["display_text"][1][0] = "201900.00%"
    assert outcome_issues(state)[0]["code"] == "calculation.year_display_mismatch"


def test_read_audit_still_owns_the_next_turn_before_calculation_recovery():
    state = source_state()
    state.read_audit = {"status": "review_pending", "event_step": 3}
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused/v1", read_audit_gate=True),
        object(),
        model_client=SimpleNamespace(client=object()),
    )
    assert {t["function"]["name"] for t in agent.tools(state)} == {"read_audit"}
    result = agent.execute_proposal(
        state,
        {
            "tool": "read_audit",
            "arguments_raw": json.dumps(
                {
                    "event_step": 3,
                    "verdict": "sufficient",
                    "reason": "Source labels, years and values are present",
                    "missing_evidence": [],
                    "next_action": "continue",
                    "next_arguments_json": "{}",
                }
            ),
            "_model_visible_tools": agent.tools(state),
        },
    )
    assert result.executed, result.error
    assert "adapter__cells_set_formulas" in {
        t["function"]["name"] for t in agent.tools(state)
    }
