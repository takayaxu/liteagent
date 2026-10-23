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


def test_final_read_is_scoped_to_calculated_outputs_and_preserves_source_identity():
    state = completed_state()
    payload = state.events[-1].result["context_hint"]
    state.events[-1].proposed["arguments"]["range"] = "I11:J13"
    payload["range"] = "I11:J13"
    for key in ("values", "display_text", "formulas", "kinds"):
        payload[key] = [row[1:] for row in payload[key][1:]]
    # A post-save read of only the calculated scope is sufficient; the
    # immutable headers and year labels were already observed natively.
    assert outcome_issues(state) == []
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
    assert "adapter__range_write" in {
        t["function"]["name"] for t in agent.tools(state)
    }
    assert "adapter__cells_set_formulas" not in {
        t["function"]["name"] for t in agent.tools(state)
    }


def test_formula_text_failure_explains_atomic_rejection_once():
    args = write_args()
    for row in args["values"][1:]:
        row[1:] = [cell["value"] for cell in row[1:]]
    errors = argument_errors(source_state(), "range.write", args)
    assert len(errors) == 1
    assert "plain" not in errors[0] or "literal text" in errors[0]
    assert '"kind":"formula"' in errors[0]
    assert "none of its year labels or values were written" in errors[0]
    assert "precomputed literal" not in errors[0]


def test_reference_rejection_names_observed_and_required_cells():
    args = write_args()
    args["values"][1][1]["value"] = "='Source data'.F5/'Source data'.F4-1"
    errors = argument_errors(source_state(), "range.write", args)
    assert "observed" in errors[0] and "required" in errors[0]
    assert "F4" in errors[0] and "F6" in errors[0]
    assert "source rows and destination rows are independent" in errors[0]


def test_compact_recovery_keeps_native_source_pair_facts_without_generating_answers():
    from integrations.lite_agent.calc_formula_contract import model_evidence

    state = source_state()
    evidence = model_evidence(state)
    first = evidence["pairs"][0]
    assert first["year"] == 2019
    assert first["current"] == {"sheet": "Source data", "cell": "F6", "value": 125}
    assert first["previous"] == {"sheet": "Source data", "cell": "F5", "value": 100}
    assert first["observed_destination"] is None
    assert "formula" not in first and "expected_result" not in first
    state.events.append(event(4, "range.write", write_args()))
    state.events.append(
        event(
            5, "cells.set_formulas", {"sheet": "Changes", "writes": []}, executed=False
        )
    )
    state.events[-1].validated = False
    # 4-turn recovery intentionally omits part of the history, but the source
    # projection must still be reconstructed from the immutable observations.
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused/v1", include_gui=False),
        object(),
        model_client=SimpleNamespace(client=object()),
    )
    messages = agent._messages(
        state, b"invalid-image", tools=agent.tools(state), execution_recovery=True
    )
    text = next(
        item["text"] for item in messages[-1]["content"] if item["type"] == "text"
    )
    native = json.loads(text.split("calculation_source_cells:\n")[1])
    assert native["pairs"][0]["current"]["cell"] == "F6"
    assert native["pairs"][0]["observed_destination"] == "I11"
    limited = model_evidence(state, limit=1)
    assert len(limited["pairs"]) == 1 and limited["omitted_pairs"] == 5


def test_header_or_year_write_does_not_project_calculation_as_mutation_complete():
    state = source_state()
    args = write_args()
    args["values"] = [
        ["Year", "Cash change", "Equipment change"],
        [2019, None, None],
        [2020, None, None],
        [2021, None, None],
    ]
    state.events.append(event(4, "range.write", args))
    progress = state.workflow_progress()
    assert progress["pending_phase"] == "outcome_verification"
    assert (
        progress["outstanding_outcomes"][0]["code"] == "calculation.output_unverified"
    )


@pytest.mark.parametrize(
    "area,values",
    [
        ("H11:H13", [[2019, 2020, 2021]]),
        (
            "I11:J13",
            [{"kind": "formula", "value": "='Source data'.F6/'Source data'.F5-1"}] * 6,
        ),
        ("H10:K13", write_args()["values"]),
    ],
)
def test_invalid_matrix_geometry_is_rejected_before_inventing_cell_roles(area, values):
    args = {"sheet": "Changes", "range": area, "values": values}
    errors = argument_errors(source_state(), "range.write", args)
    assert len(errors) == 1
    assert "RANGE_INVALID" in errors[0]
    assert "No cells were written" in errors[0]
    assert "precomputed literal" not in errors[0]


def test_failed_typed_matrix_reopens_labels_before_explicit_formula_records():
    """Replay the failure with shifted sheets/rows, partial labels and a repair."""
    from integrations.lite_agent.calc_formula_contract import model_evidence
    from jsonschema import Draft202012Validator

    state = source_state()
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused/v1", include_gui=False),
        object(),
        model_client=SimpleNamespace(client=object()),
    )
    args = write_args()
    state.events.append(event(4, "range.write", {
        "sheet": "Changes", "range": "H10:J10", "values": args["values"][0],
    }))
    flat = {"sheet": "Changes", "range": "I11:J13", "values": [cell for row in args["values"][1:] for cell in row[1:]]}
    errors = argument_errors(state, "range.write", flat)
    assert "RANGE_INVALID" in errors[0]
    rejected = event(5, "range.write", flat, executed=False)
    rejected.error = {"type": "ValueError", "detail": errors[0]}
    state.events.append(rejected)

    def visible():
        return {tool["function"]["name"]: tool["function"] for tool in agent.tools(state)}

    tools = visible()
    assert "adapter__range_read" in tools
    assert "adapter__cells_set_formulas" not in tools
    evidence = model_evidence(state)["destination_labels"]
    assert evidence["headers_observed"]
    assert evidence["missing_year_labels"] == [2019, 2020, 2021]
    assert evidence["observed_year_column"] == "H"
    schema = tools["adapter__range_write"]["parameters"]
    assert not list(Draft202012Validator(schema).iter_errors({"sheet": "Changes", "range": "H11:H13", "values": [2019, 2020, 2021]}))
    assert list(Draft202012Validator(schema).iter_errors(flat))
    assert "typed" not in tools["adapter__range_write"]["parameters"]["properties"]["values"]["description"] or "do not" in tools["adapter__range_write"]["parameters"]["properties"]["values"]["description"]

    state.events.append(event(6, "range.write", {"sheet": "Changes", "range": "H11:H12", "values": [2019, 2020]}))
    assert "adapter__cells_set_formulas" not in visible()
    assert model_evidence(state)["destination_labels"]["missing_year_labels"] == [2021]
    state.events.append(event(7, "range.write", {"sheet": "Changes", "range": "H13", "values": [2021]}))
    tools = visible()
    assert "adapter__cells_set_formulas" in tools
    assert model_evidence(state)["destination_labels"]["ready_for_formulas"]
    formulas = {"sheet": "Changes", "writes": [
        {"cell": f"{column}{row}", "formula": args["values"][row - 10][index]["value"]}
        for row in range(11, 14) for column, index in (("I", 1), ("J", 2))
    ]}
    assert not list(Draft202012Validator(tools["adapter__cells_set_formulas"]["parameters"]).iter_errors(formulas))
    assert argument_errors(state, "cells.set_formulas", formulas) == []
    # Evidence, rather than an earlier successful writer call, owns reopening.
    state.events.append(event(8, "range.write", {"sheet": "Changes", "range": "H13", "values": [None]}))
    assert "adapter__cells_set_formulas" not in visible()
    errors = argument_errors(state, "cells.set_formulas", formulas)
    assert "Missing year labels: [2021]" in errors[0]


def test_formula_surface_change_does_not_change_unrelated_writer_schema():
    from integrations.lite_agent.calc_formula_contract import constrain_tools

    state = source_state()
    state.instruction = "Write an inventory table and formulas as requested."
    tools = build_tools(state.domain, ["range.write", "cells.set_formulas"], include_gui=False)
    original = deepcopy(tools)
    assert constrain_tools(tools, state) == original
