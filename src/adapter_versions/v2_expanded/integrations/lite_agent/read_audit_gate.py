"""Opt-in Calc content-read review; model judges evidence, runtime enforces repair."""
from __future__ import annotations

import copy
import json
from typing import Any

from .tool_catalog import build_tools
from .tool_validation import validate_model_visible_tool_arguments

AUDIT_TOOL = {
    'type': 'function', 'function': {
        'name': 'read_audit',
        'description': 'Submit the mandatory review of a read result before any dependent operation. Evaluate sufficiency for the user task, not merely whether the call succeeded.',
        'parameters': {
            'type': 'object', 'properties': {
                'event_step': {'type': 'integer', 'minimum': 1},
                'verdict': {'type': 'string', 'enum': ['sufficient', 'insufficient', 'unknown']},
                'reason': {'type': 'string', 'minLength': 1},
                'missing_evidence': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}, 'description': 'List actual missing inputs. Use [] when sufficient.'},
                'next_action': {'type': 'string', 'enum': ['continue', 'range.read', 'workbook.inspect', 'tools_search']},
                'next_arguments_json': {'type': 'string', 'description': 'A JSON object containing your next read/inspection/search arguments; use {} when next_action is continue.'},
            },
            'required': ['event_step', 'verdict', 'reason', 'missing_evidence', 'next_action', 'next_arguments_json'],
            'additionalProperties': False,
        },
    },
}



def active(agent, state):
    return agent.config.read_audit_gate and state.domain == "libreoffice_calc"


def gate_tools(agent, state):
    if not active(agent, state):
        return None
    gate = state.read_audit
    if not gate or gate["status"] == "passed":
        return None
    if gate["status"] == "review_pending":
        return [copy.deepcopy(AUDIT_TOOL)]
    # Lease overrides phase filters. Inspection/search cannot discharge the
    # missing content: only a successful read followed by a new review can.
    return [t for t in build_tools(state.domain, ["range.read", "workbook.inspect"],
                include_gui=False, strict_generic=True)
            if t["function"]["name"] != "propose_done"]


def messages(agent, state, protocol_error=None):
    if gate_tools(agent, state) is None:
        return None
    evidence = [{"step": e.step, "action": e.proposed.get("action") or e.proposed.get("tool"),
                 "arguments": e.proposed.get("arguments"), "executed": e.executed,
                 "result": e.result, "error": e.error} for e in state.events]
    reviewing = state.read_audit["status"] == "review_pending"
    system = (
        "You are reviewing a desktop agent read result. Call only read_audit once. "
        "Compare the actual returned object, rows, columns, labels, values and truncation "
        "against the inputs needed for the user task. A successful read of the requested "
        "window is not proof of task-input sufficiency. Do not require the entire used "
        "range if the task only needs a smaller scope. Do not guess missing labels or "
        "values. If insufficient or uncertain, describe the gap and choose a bounded "
        "public read/inspect/search with your own arguments. If sufficient, choose "
        "continue with {}. This call cannot edit the application or complete the task."
    ) if reviewing else (
        "The mandatory read review found missing task evidence. Its verdict supersedes "
        "automatic source-complete milestones. Use the restored public read/inspection "
        "tools to fill the named gap before any mutation. Actually call a public tool; "
        "describing a next action does not execute it. Inspect/search alone cannot close "
        "this repair: read the missing content, which will receive a new review. "
        "Choose arguments yourself using the task, review and real observations. "
        "If recovery is impossible, fail_task with a concrete reason."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps({
        "instruction": state.instruction, "read_event_step": state.read_audit["event_step"],
        "read_audit": state.read_audit, "events": evidence,
        "protocol_error": protocol_error,
    }, ensure_ascii=False)}]


def enforce(agent, state, tool):
    tools = gate_tools(agent, state)
    if tools is not None and tool not in {t["function"]["name"] for t in tools}:
        raise ValueError("mandatory read review/repair must finish before dependent operations")


def submit(agent, state, arguments):
    if not active(agent, state) or not state.read_audit or state.read_audit["status"] != "review_pending":
        raise ValueError("read_audit requires a pending content-read result")
    validate_model_visible_tool_arguments([AUDIT_TOOL], "read_audit", arguments)
    if arguments["event_step"] != state.read_audit["event_step"]:
        raise ValueError("review must refer to the pending read event")
    next_args = json.loads(arguments["next_arguments_json"])
    if not isinstance(next_args, dict):
        raise ValueError("next arguments must decode to an object")
    if arguments["verdict"] == "sufficient":
        if arguments["next_action"] != "continue" or next_args or arguments["missing_evidence"]:
            raise ValueError("sufficient verdict contradicts missing evidence or repair request")
        status = "passed"
    else:
        action = arguments["next_action"]
        if action == "continue" or not arguments["missing_evidence"]:
            raise ValueError("incomplete/unknown review requires a named gap and recovery action")
        tools = build_tools(state.domain, [] if action == "tools_search" else [action],
                            include_gui=False, strict_generic=True)
        expected = next(t for t in tools if t["function"]["name"] == (
            action if action == "tools_search" else "adapter__" + action.replace(".", "_")))
        validate_model_visible_tool_arguments([expected], expected["function"]["name"], next_args)
        status = "repair_pending"
    state.read_audit = {"status": status, **copy.deepcopy(arguments)}
    return copy.deepcopy(state.read_audit)


def observe(agent, state, event):
    if active(agent, state) and event.executed and event.proposed.get("action") == "range.read":
        state.read_audit = {"status": "review_pending", "event_step": event.step}
