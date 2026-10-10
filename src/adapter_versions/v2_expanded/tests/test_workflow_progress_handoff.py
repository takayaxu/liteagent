from __future__ import annotations

from types import SimpleNamespace

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


class _Executor:
    pass


def _state(instruction: str) -> RuntimeState:
    return RuntimeState(task_id="workflow-progress", domain="multi_apps", instruction=instruction)


def _event(step: int, action: str, params: dict, result: dict) -> ExecutionEvent:
    adapter = "os" if action == "filesystem.find" else "libreoffice_calc"
    return ExecutionEvent(
        step=step,
        timestamp_utc="2026-10-03T00:00:00Z",
        proposed={
            "kind": "adapter",
            "action": "adapter.call",
            "arguments": {
                "adapter": adapter,
                "action": action,
                "payload": {"params": params},
            },
        },
        executed=True,
        result=result,
    )


def test_workflow_progress_is_first_marker_after_bounded_context_projection():
    state = _state("Read the payment record and add the matching recipients to the draft.")
    path = "/home/user/Documents/tuition_payment.xlsx"
    state.events.extend(
        [
            _event(
                1,
                "filesystem.find",
                {"roots": ["~/Documents"], "name_patterns": ["tuition_payment.xlsx"]},
                {"context_hint": {"matches": [{"path": path}]}},
            ),
            _event(
                2,
                "workbook.read_file",
                {"path": path},
                {
                    "context_hint": {
                        "context_truncated": True,
                        "downstream_context": {
                            "path": path,
                            "truncated": False,
                            "sheets_truncated": False,
                        },
                    }
                },
            ),
        ]
    )

    summary = state.context_summary(limit=1, strict_generic=True)

    assert summary[0]["workflow_progress"]["pending_phase"] == "target_action_discovery"
    assert path in summary[0]["workflow_progress"]["discovered_files"]
    assert path in summary[0]["workflow_progress"]["opened_sources"]
    assert summary[0]["workflow_progress"]["read_sources"][0]["complete"] is True


def test_incomplete_source_read_does_not_trigger_target_handoff():
    state = _state("Read the record and add the matching recipients to the draft.")
    state.events.append(
        _event(
            1,
            "workbook.read_file",
            {"path": "/tmp/record.xlsx"},
            {"context_hint": {"downstream_context": {"truncated": True, "source_has_more": True}}},
        )
    )

    assert state.source_read_handoff_pending() is False
    assert state.workflow_progress()["pending_phase"] == "source_read"


def test_complete_source_read_exposes_search_for_next_multi_app_mutation():
    instruction = (
        "I've drafted an e-mail reminder for those who haven't paid tuition. "
        "Check their e-mails from the payment record and add them to the receiver field."
    )
    state = _state(instruction)
    state.events.extend(
        [
            _event(
                1,
                "filesystem.find",
                {"roots": ["~/Documents"], "name_patterns": ["tuition_payment.xlsx"]},
                {"context_hint": {"matches": [{"path": "/tmp/record.xlsx"}]}},
            ),
            _event(
                2,
                "workbook.read_file",
                {"path": "/tmp/record.xlsx"},
                {"context_hint": {"downstream_context": {"truncated": False}}},
            ),
        ]
    )
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused", include_gui=False),
        _Executor(),
        model_client=SimpleNamespace(client=object()),
    )

    tools = agent.tools(state)

    assert [tool["function"]["name"] for tool in tools] == ["tools_search"]
    assert "Do not reread it" in tools[0]["function"]["description"]
    assert "thunderbird.compose.set_recipients" in tools[0]["function"]["description"]
    assert "mail.compose_recipients" in tools[0]["function"]["description"]


def test_mail_recipient_handoff_rejects_calc_only_catalog_result():
    state = _state(
        "Read the payment record and add the matching e-mail recipients to the draft."
    )
    state.events.extend(
        [
            _event(
                1,
                "workbook.read_file",
                {"path": "/tmp/record.xlsx"},
                {"context_hint": {"downstream_context": {"truncated": False}}},
            ),
            ExecutionEvent(
                step=2,
                timestamp_utc="2026-10-03T00:00:00Z",
                proposed={
                    "kind": "catalog",
                    "action": "tools_search",
                    "arguments": {"query": "libreoffice_calc workbook.write_cell"},
                },
                executed=True,
                result={
                    "matches": [
                        {
                            "action": "adapter.call",
                            "adapter": "libreoffice_calc",
                            "downstream_action": "range.write",
                        }
                    ]
                },
            ),
        ]
    )

    assert state.requested_mail_recipient_target() is True
    assert state.source_read_handoff_pending() is True


def test_mail_recipient_handoff_accepts_only_mail_target_route():
    state = _state(
        "Read the payment record and add the matching e-mail recipients to the draft."
    )
    state.events.extend(
        [
            _event(
                1,
                "workbook.read_file",
                {"path": "/tmp/record.xlsx"},
                {"context_hint": {"downstream_context": {"truncated": False}}},
            ),
            ExecutionEvent(
                step=2,
                timestamp_utc="2026-10-03T00:00:00Z",
                proposed={
                    "kind": "catalog",
                    "action": "tools_search",
                    "arguments": {"query": "thunderbird.compose.set_recipients"},
                },
                executed=True,
                result={
                    "matches": [
                        {
                            "action": "adapter.call",
                            "adapter": "thunderbird",
                            "downstream_action": "compose.set_recipients",
                        }
                    ]
                },
            ),
        ]
    )

    assert state.source_read_handoff_pending() is False


def test_calc_write_instruction_does_not_trigger_mail_target_lease():
    state = _state("Read the payment record and write the total into the Calc sheet.")
    state.events.append(
        _event(
            1,
            "workbook.read_file",
            {"path": "/tmp/record.xlsx"},
            {"context_hint": {"downstream_context": {"truncated": False}}},
        )
    )

    assert state.requested_mail_recipient_target() is False


def test_successful_catalog_search_advances_past_source_handoff():
    state = _state("Read the record and add the matching recipients to the draft.")
    state.events.append(
        _event(
            1,
            "workbook.read_file",
            {"path": "/tmp/record.xlsx"},
            {"context_hint": {"downstream_context": {"truncated": False}}},
        )
    )
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-10-03T00:00:00Z",
            proposed={"kind": "catalog", "action": "tools_search", "arguments": {"query": "recipient"}},
            executed=True,
            result={
                "matches": [
                    {
                        "action": "adapter.call",
                        "adapter": "thunderbird",
                        "downstream_action": "compose.set_recipients",
                    }
                ]
            },
        )
    )

    assert state.source_read_handoff_pending() is False


def test_read_only_instruction_keeps_normal_surface():
    state = _state("Inspect the current application state.")
    state.events.append(
        _event(
            1,
            "workbook.read_file",
            {"path": "/tmp/record.xlsx"},
            {"context_hint": {"downstream_context": {"truncated": False}}},
        )
    )

    assert state.source_read_handoff_pending() is False
