from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.semantic_requirements import strict_semantic_requirement_errors
from integrations.lite_agent.execution_engine import _organization_route_lease
from integrations.lite_agent.tool_surface import _latest_explicit_search_routes

from integrations.lite_agent.search_recovery_tools import (
    _downstream_params_schema,
    constrain_adapter_call_routes,
)
from integrations.lite_agent.tool_catalog import DIRECT_ACTION_SCHEMAS, build_tools, search_actions
from integrations.lite_agent.organization_validation import VERIFY_ACTION, VERIFY_TOOL
from integrations.lite_agent.model_client import StructuredToolProtocolError


def _os_actions(domain: str, query: str) -> set[str]:
    hits = search_actions(domain, query, strict_generic=True, limit=7)
    return {
        hit["downstream_action"] if domain == "multi_apps" else hit["action"]
        for hit in hits
        if domain != "multi_apps" or hit.get("adapter") == "os"
    }


@pytest.mark.parametrize("domain", ["os", "multi_apps"])
@pytest.mark.parametrize(
    "query",
    [
        "move files and directories into folders",
        "file manager desktop organization",
        "organize files into folders",
    ],
)
def test_move_and_folder_organization_discover_rename(domain: str, query: str) -> None:
    assert "filesystem.rename" in _os_actions(domain, query)


@pytest.mark.parametrize(
    "query, expected",
    [
        ("filesystem.find kind=any roots=/home/user/Documents/Papers", "filesystem.find"),
        ("filesystem.rename move file to directory", "filesystem.rename"),
    ],
)
def test_explicit_filesystem_search_returns_only_the_requested_route(
    query: str, expected: str
) -> None:
    assert _os_actions("multi_apps", query) == {expected}


@pytest.mark.parametrize("domain", ["os", "multi_apps"])
def test_explicit_copy_request_keeps_copy_discoverable(domain: str) -> None:
    assert "filesystem.copy" in _os_actions(domain, "copy a file to another folder")


def _organization_state(kind: str = "any") -> RuntimeState:
    state = RuntimeState(
        task_id="organize-test",
        domain="multi_apps",
        instruction="Organize the files and folders on the Desktop into category folders.",
    )
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-01-01T00:00:00+00:00",
            proposed={
                "kind": "adapter",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "filesystem.find",
                    "payload": {
                        "params": {
                            "roots": ["~/Desktop"],
                            "kind": kind,
                            "recursive": False,
                        }
                    },
                },
            },
            executed=True,
            result={
                "context_hint": {
                    "downstream_adapter": "os",
                    "downstream_action": "filesystem.find",
                    "downstream_context": {
                        "kind": kind,
                        "truncated": False,
                        "matches": [
                            {"path": "/home/user/Desktop/project", "kind": "directory"},
                            {"path": "/home/user/Desktop/paper.pdf", "kind": "file"},
                        ],
                    },
                }
            },
        )
    )
    return state


class _NoopExecutor:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("Adapter execution is not expected")


def test_broad_inventory_search_preserves_the_find_route_and_schema():
    state = RuntimeState(
        task_id="inventory-search", domain="multi_apps",
        instruction="Organize the files and folders on the Desktop into category folders.",
    )
    query = "filesystem list files desktop"
    matches = search_actions("multi_apps", query, strict_generic=True, limit=6)
    assert len(matches) > 1
    assert any(hit.get("downstream_action") == "filesystem.find" for hit in matches)
    state.events.append(ExecutionEvent(
        step=1, timestamp_utc="2026-01-01T00:00:00Z", executed=True,
        proposed={"kind": "catalog", "tool": "tools_search", "arguments": {"query": query}},
        result={"status": "ok", "executed": True, "matches": matches},
    ))
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), _NoopExecutor())

    tools = agent.tools(state)
    assert [tool["function"]["name"] for tool in tools] == ["adapter__adapter_call"]
    schema = tools[0]["function"]["parameters"]
    assert schema["x-allowed-routes"] == [{"adapter": "os", "action": "filesystem.find"}]
    params = schema["properties"]["payload"]["properties"]["params"]
    assert params["properties"]["kind"]["enum"] == ["any"]
    assert params["properties"]["recursive"]["enum"] == [False]
    assert {"roots", "name_patterns", "kind", "recursive"} <= set(params["required"])
    assert len(agent.tool_catalog_hash(state)) == 64


def _checked(state, path, directory, disposition="move"):
    observation = state.filesystem_organization_evidence({"path": path})
    state.events.append(ExecutionEvent(
        step=len(state.events) + 1, timestamp_utc="2026-01-01T00:00:01Z",
        proposed={"kind": "organization", "action": VERIFY_ACTION, "arguments": {"path": path}},
        executed=True, result={
            "path": path, "passed": True, "disposition": disposition,
            "destination_directory": directory, "instruction": state.instruction,
            "observation_step": observation["step"] if observation else None,
        },
    ))


def test_pending_organization_keeps_search_and_rename_surface() -> None:
    state = _organization_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": "/home/user/Desktop/main.py", "name": "main.py", "kind": "file"}
    ]
    _checked(state, "/home/user/Desktop/main.py", "/home/user/Desktop/Code")
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused", include_gui=False),
        _NoopExecutor(),  # type: ignore[arg-type]
    )

    tools = agent.tools(state)
    names = {tool["function"]["name"] for tool in tools}
    assert "tools_search" in names
    adapter = next(
        tool["function"]
        for tool in tools
        if tool["function"].get("name") == "adapter__adapter_call"
    )
    assert adapter["parameters"]["x-allowed-routes"] == [
        {"adapter": "os", "action": "filesystem.rename"}
    ]


def test_natural_language_reader_search_promotes_only_current_reader() -> None:
    state = _organization_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {
            "path": "/home/user/Desktop/statement.pdf",
            "name": "statement.pdf",
            "kind": "file",
        }
    ]
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-01-01T00:00:01+00:00",
            proposed={
                "kind": "catalog",
                "action": "tools_search",
                "arguments": {"query": "read PDF content from the statement"},
            },
            executed=True,
            result={
                "matches": [
                    {"adapter": "os", "downstream_action": "filesystem.find"},
                    {"adapter": "os", "downstream_action": "pdf.extract_text_batch"},
                    {"adapter": "os", "downstream_action": "filesystem.rename"},
                ]
            },
        )
    )

    assert _latest_explicit_search_routes(state) == [
        ("os", "pdf.extract_text_batch")
    ]


def test_read_search_without_read_intent_does_not_promote_reader() -> None:
    state = _organization_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {
            "path": "/home/user/Desktop/statement.pdf",
            "name": "statement.pdf",
            "kind": "file",
        }
    ]
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-01-01T00:00:01+00:00",
            proposed={
                "kind": "catalog",
                "action": "tools_search",
                "arguments": {"query": "find invoices on Desktop"},
            },
            executed=True,
            result={
                "matches": [
                    {"adapter": "os", "downstream_action": "pdf.extract_text_batch"},
                ]
            },
        )
    )

    assert _latest_explicit_search_routes(state) == []


def test_skip_current_marks_retained_object_and_advances() -> None:
    state = _organization_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {
            "path": "/home/user/Desktop/statement.pdf",
            "name": "statement.pdf",
            "kind": "file",
        },
        {
            "path": "/home/user/Desktop/invoice.pdf",
            "name": "invoice.pdf",
            "kind": "file",
        },
    ]
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-01-01T00:00:01+00:00",
            proposed={
                "kind": "adapter",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "pdf.extract_text_batch",
                    "payload": {
                        "params": {
                            "input_pattern": "/home/user/Desktop/statement.pdf",
                            "cwd_source": "explicit",
                            "cwd_path": "/home/user/Desktop",
                        }
                    },
                },
            },
            executed=True,
            result={
                "context_hint": {
                    "files": [
                        {
                            "path": "/home/user/Desktop/statement.pdf",
                            "status": "ok",
                            "text": "statement",
                        }
                    ]
                }
            },
        )
    )
    _checked(state, "/home/user/Desktop/statement.pdf", "/home/user/Desktop", "retain")
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused", include_gui=False),
        _NoopExecutor(),  # type: ignore[arg-type]
    )

    names = {tool["function"]["name"] for tool in agent.tools(state)}
    assert "organization__skip_current" in names
    event = agent.execute_proposal(
        state,
        {
            "tool": "organization__skip_current",
            "arguments_raw": (
                '{"path":"/home/user/Desktop/statement.pdf",'
                '"reason":"bank statement is retained and is not an invoice"}'
            ),
        },
    )

    assert event.executed is True
    assert state.filesystem_organization_pending_entries() == [
        "/home/user/Desktop/invoice.pdf"
    ]
    assert state.filesystem_organization_current_entry()["path"] == (
        "/home/user/Desktop/invoice.pdf"
    )
    skipped = state.filesystem_organization_progress()["objects"][
        "/home/user/Desktop/statement.pdf"
    ]
    assert skipped["classified"] is True
    assert skipped["moved"] is False
    assert skipped["skipped"] is True


def test_read_bank_statement_exposes_skip_without_rename() -> None:
    state = RuntimeState(
        task_id="billing-organize-test",
        domain="multi_apps",
        instruction=(
            "Compare invoices with the bank statement transactions and move "
            "unmatched invoice files into Problematic."
        ),
    )
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-01-01T00:00:00+00:00",
            proposed={
                "kind": "adapter",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "filesystem.find",
                    "payload": {"params": {"roots": ["~/Desktop"], "kind": "any"}},
                },
            },
            executed=True,
            result={
                "context_hint": {
                    "downstream_context": {
                        "matches": [
                            {
                                "path": "/home/user/Desktop/Bank-Statement.pdf",
                                "name": "Bank-Statement.pdf",
                                "kind": "file",
                            },
                            {
                                "path": "/home/user/Desktop/Invoice-1.pdf",
                                "name": "Invoice-1.pdf",
                                "kind": "file",
                            },
                        ]
                    }
                }
            },
        )
    )
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-01-01T00:00:01+00:00",
            proposed={
                "kind": "adapter",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "pdf.extract_text_batch",
                    "payload": {
                        "params": {
                            "input_pattern": "/home/user/Desktop/Bank-Statement.pdf"
                        }
                    },
                },
            },
            executed=True,
            result={
                "files": [
                    {
                        "path": "/home/user/Desktop/Bank-Statement.pdf",
                        "status": "ok",
                        "text": "Bank Statement\nTransactions\nAcme LLC 100.00",
                    }
                ]
            },
        )
    )
    _checked(state, "/home/user/Desktop/Bank-Statement.pdf", "/home/user/Desktop", "retain")
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused", include_gui=False),
        _NoopExecutor(),  # type: ignore[arg-type]
    )
    names = {tool["function"]["name"] for tool in agent.tools(state)}
    assert "organization__skip_current" in names
    assert "adapter__adapter_call" not in names
    assert names == {"organization__skip_current"}


def test_skip_current_requires_content_for_ambiguous_object() -> None:
    state = _organization_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {
            "path": "/home/user/Desktop/statement.pdf",
            "name": "statement.pdf",
            "kind": "file",
        }
    ]
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused", include_gui=False),
        _NoopExecutor(),  # type: ignore[arg-type]
    )

    event = agent.execute_proposal(
        state,
        {
            "tool": "organization__skip_current",
            "arguments_raw": (
                '{"path":"/home/user/Desktop/statement.pdf",'
                '"reason":"not an invoice"}'
            ),
        },
    )

    assert event.executed is False
    assert "passed independent classification" in event.error["detail"]


def test_explicit_find_search_is_not_replaced_by_batch_consumer_route() -> None:
    state = RuntimeState(
        task_id="pdf-table-search",
        domain="multi_apps",
        instruction=(
            "Extract the first author from each paper in the folder and organize "
            "them in an Excel table. Save the table as authors.xlsx."
        ),
    )
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-01-01T00:00:00+00:00",
            proposed={
                "kind": "adapter",
                "action": "pdf.extract_text_batch",
                "arguments": {
                    "input_pattern": "paper.pdf",
                    "cwd_source": "explicit",
                    "cwd_path": "/home/user/Documents/Papers",
                },
            },
            executed=True,
            result={
                "context_hint": {
                    "input_pattern": "paper.pdf",
                    "matched_count": 1,
                    "files": [
                        {
                            "path": "/home/user/Documents/Papers/paper.pdf",
                            "status": "ok",
                            "text": "First Author",
                        }
                    ],
                }
            },
        )
    )
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused", include_gui=False),
        _NoopExecutor(),  # type: ignore[arg-type]
    )

    event = agent.execute_proposal(
        state,
        {
            "tool": "tools_search",
            "arguments_raw": '{"query":"filesystem.find kind=any roots=/home/user/Documents/Papers"}',
        },
    )

    assert [item["downstream_action"] for item in event.result["matches"]] == [
        "filesystem.find"
    ]


def test_kind_any_find_sets_classify_and_move_marker() -> None:
    state = _organization_state()

    marker = state.filesystem_observation_state()

    assert marker is not None
    assert marker["complete"] is True
    assert marker["next_required_phase"] == "classify_and_move"
    assert marker["observed_roots"] == ["~/Desktop"]
    assert {item["path"] for item in marker["observed_entries"]} == {
        "/home/user/Desktop/project",
        "/home/user/Desktop/paper.pdf",
    }
    assert state.context_summary(strict_generic=True)[0]["filesystem_observation"][
        "next_required_phase"
    ] == "classify_and_move"


def test_file_only_find_does_not_mark_observation_complete() -> None:
    assert _organization_state("file").filesystem_observation_state() is None


def test_organize_table_results_is_not_filesystem_organization() -> None:
    state = RuntimeState(
        task_id="table-organize-test",
        domain="multi_apps",
        instruction="Extract the reports and organize the results in a table.",
    )

    assert state.filesystem_organization_requested() is False
    assert state.filesystem_observation_state() is None


def test_organization_pending_entries_follow_successful_renames() -> None:
    state = _organization_state()
    _checked(state, "/home/user/Desktop/paper.pdf", "/home/user/Desktop/Paper_reading")
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-01-01T00:00:01+00:00",
            proposed={
                "kind": "adapter",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "filesystem.rename",
                    "payload": {
                        "params": {
                            "source": "/home/user/Desktop/paper.pdf",
                            "destination": "/home/user/Desktop/Paper_reading/paper.pdf",
                        }
                    },
                },
            },
            executed=True,
            result={"verification_passed": True},
        )
    )

    assert "/home/user/Desktop/paper.pdf" not in state.filesystem_organization_pending_entries()
    assert state.filesystem_organization_complete() is False


def test_organization_completion_requires_all_observed_objects_to_move() -> None:
    state = _organization_state()

    errors = strict_semantic_requirement_errors(state)
    assert any("2 object(s) remain pending" in error for error in errors)

    for step, source, destination in (
        (
            2,
            "/home/user/Desktop/project",
            "/home/user/Desktop/Projects/project",
        ),
        (
            3,
            "/home/user/Desktop/paper.pdf",
            "/home/user/Desktop/Paper_reading/paper.pdf",
        ),
    ):
        _checked(state, source, destination.rsplit("/", 1)[0])
        state.events.append(
            ExecutionEvent(
                step=step,
                timestamp_utc="2026-01-01T00:00:01+00:00",
                proposed={
                    "kind": "adapter",
                    "action": "adapter.call",
                    "arguments": {
                        "adapter": "os",
                        "action": "filesystem.rename",
                        "payload": {"params": {"source": source, "destination": destination}},
                    },
                },
                executed=True,
                result={"verification_passed": True},
            )
        )

    assert not any("filesystem organization is incomplete" in error for error in strict_semantic_requirement_errors(state))


def test_authoritative_inventory_survives_context_omission() -> None:
    state = _organization_state()
    state.filesystem_organization_inventory = [
        {"path": "/home/user/Desktop/project", "kind": "directory"},
        {"path": "/home/user/Desktop/paper.pdf", "kind": "file"},
        {"path": "/home/user/Desktop/notes.docx", "kind": "file"},
    ]
    # The model-facing projection contains only a bounded prefix.
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": "/home/user/Desktop/project", "kind": "directory"}
    ]
    state.events[0].result["context_hint"]["downstream_context"]["matches_omitted"] = 2

    assert state.filesystem_organization_pending_entries() == [
        "/home/user/Desktop/notes.docx",
        "/home/user/Desktop/paper.pdf",
        "/home/user/Desktop/project",
    ]


def test_ambiguous_current_object_requires_content_before_move() -> None:
    state = _organization_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": "/home/user/Desktop/paper.pdf", "name": "paper.pdf", "kind": "file"},
    ]
    current = state.filesystem_organization_current_entry()
    assert current is not None
    assert state.filesystem_organization_requires_content(current) is True
    assert state.filesystem_organization_reader_route(current) == (
        "os",
        "pdf.extract_text_batch",
    )


def test_certain_source_object_can_move_without_content_reader() -> None:
    state = _organization_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": "/home/user/Desktop/main.py", "name": "main.py", "kind": "file"},
    ]
    assert state.filesystem_organization_requires_content() is False


@pytest.mark.parametrize("extension", ["csv", "ods", "xlsx"])
def test_organization_spreadsheet_reader_executes_and_unlocks_move(extension: str) -> None:
    state = _organization_state()
    path = f"/home/user/Desktop/report.{extension}"
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": path, "name": f"report.{extension}", "kind": "file"}
    ]
    executor = Mock()
    executor.execute.return_value = {
        "executed": True,
        "result": {"context_hint": {"path": path, "sheets": [{"rows": [["Observed heading"]]}]}},
    }
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), executor)
    tools = agent.tools(state)
    reader = next(tool["function"] for tool in tools if tool["function"]["name"] == "adapter__adapter_call")
    assert reader["parameters"]["x-allowed-routes"] == [
        {"adapter": "libreoffice_calc", "action": "workbook.read_file"}
    ]
    params = reader["parameters"]["properties"]["payload"]["properties"]["params"]
    assert "path" in params["required"]
    assert "path" in params["properties"]
    arguments = {
        "adapter": "libreoffice_calc", "action": "workbook.read_file",
        "payload": {"params": {"path": path}},
    }
    event = agent.execute_proposal(state, {
        "tool": "adapter__adapter_call", "arguments_raw": json.dumps(arguments),
        "_model_visible_tools": tools,
    })
    assert event.executed, event.error
    assert executor.execute.call_args.args[2] == arguments
    assert path in state.filesystem_organization_read_paths()
    assert "Observed heading" in json.dumps(state.filesystem_organization_model_context())
    assert {tool["function"]["name"] for tool in agent.tools(state)} == {VERIFY_TOOL}
    _checked(state, path, "/home/user/Desktop/Reports")
    move = next(tool["function"] for tool in agent.tools(state) if tool["function"]["name"] == "adapter__adapter_call")
    assert move["parameters"]["x-allowed-routes"] == [
        {"adapter": "os", "action": "filesystem.rename"}
    ]


@pytest.mark.parametrize("action, payload", [
    ("spreadsheet.read_file", {"params": {"path": "/home/user/Desktop/report.xlsx"}}),
    ("workbook.read_file", {"target": {"path": "/home/user/Desktop/report.xlsx"}, "params": {}}),
])
def test_organization_spreadsheet_rejects_retired_route_and_missing_params_path(action, payload) -> None:
    state = _organization_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": "/home/user/Desktop/report.xlsx", "name": "report.xlsx", "kind": "file"}
    ]
    executor = Mock()
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), executor)
    event = agent.execute_proposal(state, {
        "tool": "adapter__adapter_call",
        "arguments_raw": json.dumps({"adapter": "libreoffice_calc", "action": action, "payload": payload}),
        "_model_visible_tools": agent.tools(state),
    })
    assert not event.executed
    executor.execute.assert_not_called()


def test_unregistered_reader_route_restores_search_without_rewriting(monkeypatch, caplog) -> None:
    state = _organization_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": "/home/user/Desktop/report.xlsx", "name": "report.xlsx", "kind": "file"}
    ]
    monkeypatch.setattr(RuntimeState, "filesystem_organization_reader_route", lambda *_args: (
        "libreoffice_calc", "spreadsheet.read_file",
    ))
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), _NoopExecutor())
    tools = agent.tools(state)
    assert {tool["function"]["name"] for tool in tools} == {"tools_search"}
    assert "libreoffice_calc.spreadsheet.read_file" in tools[0]["function"]["description"]
    assert "Route configuration error" in caplog.text
    with pytest.raises(ValueError, match="Unregistered public Adapter route"):
        _downstream_params_schema("libreoffice_calc", "spreadsheet.read_file")


def test_mixed_registered_and_retired_routes_preserve_exact_valid_route() -> None:
    routes = [("libreoffice_calc", "spreadsheet.read_file"), ("os", "filesystem.rename")]
    original = list(routes)
    tools = constrain_adapter_call_routes(build_tools(
        "multi_apps", ["adapter.call"], include_gui=False,
        include_control_tools=False, strict_generic=True,
    ), routes)
    assert routes == original
    adapter = next(tool["function"] for tool in tools if tool["function"]["name"] == "adapter__adapter_call")
    assert adapter["parameters"]["x-allowed-routes"] == [
        {"adapter": "os", "action": "filesystem.rename"}
    ]
    assert any(tool["function"]["name"] == "tools_search" for tool in tools)


def test_public_action_without_detailed_schema_keeps_compatible_fallback(monkeypatch) -> None:
    monkeypatch.delitem(DIRECT_ACTION_SCHEMAS["libreoffice_calc"], "workbook.inspect")
    schema = _downstream_params_schema("libreoffice_calc", "workbook.inspect")
    assert schema["required"] == []
    assert "workbook.inspect" in schema["description"]


@pytest.mark.parametrize("adapter, action", [
    ("unknown_adapter", "workbook.read_file"),
    ("os", "workbook.read_file"),
    ("libreoffice_calc", "spreadsheet.read_file"),
])
def test_static_schema_cannot_authorize_unregistered_route(monkeypatch, adapter, action) -> None:
    monkeypatch.setitem(DIRECT_ACTION_SCHEMAS, adapter, {action: {"properties": {}, "required": []}})
    with pytest.raises(ValueError, match="Unregistered public Adapter route"):
        _downstream_params_schema(adapter, action)


@pytest.mark.parametrize(
    "destination, error_fragment",
    [
        ("/home/user/Desktop/Review queue/main.py", None),
        ("/home/user/Desktop/归档/main.py", None),
        ("/home/user/Desktop/main.py", "current model-visible schema"),
        ("/home/user/Desktop/Review queue/other.py", "current model-visible schema"),
    ],
)
def test_organization_rename_uses_model_destination(
    destination: str, error_fragment: str | None
) -> None:
    state = _organization_state()
    state.instruction = 'Move source files into the "Review queue" or "归档" folders.'
    source = "/home/user/Desktop/main.py"
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": source, "name": "main.py", "kind": "file"},
    ]
    directory = destination.rsplit("/", 1)[0] if error_fragment is None else "/home/user/Desktop/Review queue"
    _checked(state, source, directory)
    executor = Mock()
    executor.execute.return_value = {"executed": True, "result": {"status": "ok", "verification_passed": True}}
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused", include_gui=False), executor
    )
    arguments = {
        "adapter": "os",
        "action": "filesystem.rename",
        "payload": {"params": {"source": source, "destination": destination}},
    }

    event = agent.execute_proposal(
        state,
        {
            "tool": "adapter__adapter_call",
            "arguments_raw": json.dumps(arguments),
            "_model_visible_tools": agent.tools(state),
        },
    )

    if error_fragment is not None:
        assert event.executed is False
        assert error_fragment in event.error["detail"]
        executor.execute.assert_not_called()
    else:
        assert event.executed is True, event.error
        assert executor.execute.call_args.args[2] == arguments
        assert state.filesystem_organization_pending_entries() == []


def test_organization_reader_requires_full_normalized_path() -> None:
    basename_state = _organization_state()
    basename_state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": "/home/user/Desktop/paper.pdf", "name": "paper.pdf", "kind": "file"}
    ]
    basename_arguments = {
        "adapter": "os",
        "action": "pdf.extract_text_batch",
        "payload": {"params": {"input_pattern": "paper.pdf"}},
    }
    assert _organization_route_lease(
        basename_state, ("os", "pdf.extract_text_batch"), basename_arguments
    ) is False

    full_path_state = _organization_state()
    full_path_state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": "/home/user/Desktop/paper.pdf", "name": "paper.pdf", "kind": "file"}
    ]
    full_path_arguments = {
        "adapter": "os",
        "action": "pdf.extract_text_batch",
        "payload": {
            "params": {"input_pattern": "/home/user/Desktop/paper.pdf"}
        },
    }
    assert _organization_route_lease(
        full_path_state, ("os", "pdf.extract_text_batch"), full_path_arguments
    ) is True


def test_organization_progress_requires_classified_and_moved_markers() -> None:
    state = _organization_state()
    _checked(state, "/home/user/Desktop/project", "/home/user/Desktop/Projects")
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-01-01T00:00:01+00:00",
            proposed={
                "kind": "adapter",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "filesystem.rename",
                    "payload": {
                        "params": {
                            "source": "/home/user/Desktop/project",
                            "destination": "/home/user/Desktop/Projects/project",
                        }
                    },
                },
            },
            executed=True,
            result={"verification_passed": True},
        )
    )

    progress = state.filesystem_organization_progress()
    assert progress["objects"]["/home/user/Desktop/project"] == {
        "path": "/home/user/Desktop/project",
        "classified": True,
        "moved": True,
        "read": False,
        "category": "Projects",
    }
    assert progress["current_object"] == "/home/user/Desktop/paper.pdf"
    assert state.filesystem_organization_pending_entries() == [
        "/home/user/Desktop/paper.pdf"
    ]

    model_progress = state.filesystem_organization_progress(model_visible=True)
    assert model_progress == {
        "current_object": "/home/user/Desktop/paper.pdf",
        "current_object_status": {
            "classified": False,
            "moved": False,
        },
    }


def test_later_organization_prompt_binds_current_tool_lease() -> None:
    state = _organization_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": "/home/user/Desktop/paper.pdf", "name": "paper.pdf", "kind": "file"}
    ]
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-01-01T00:00:01+00:00",
            proposed={
                "kind": "adapter",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "pdf.extract_text_batch",
                    "payload": {
                        "params": {"input_pattern": "/home/user/Desktop/paper.pdf"}
                    },
                },
            },
            executed=True,
            result={
                "context_hint": {
                    "downstream_action": "pdf.extract_text_batch",
                    "files": [
                        {
                            "path": "/home/user/Desktop/paper.pdf",
                            "status": "ok",
                            "text": "invoice amount",
                        }
                    ],
                }
            },
        )
    )
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused", include_gui=False),
        _NoopExecutor(),  # type: ignore[arg-type]
    )

    tools = agent.tools(state)
    system = agent._messages(state, b"png", tools=tools)[0]["content"]

    assert "The current tool lease is authoritative" in system
    assert VERIFY_TOOL in system
    assert "Downstream routes: os.filesystem.rename" not in system
    assert "Paper_reading" not in system
    assert "Miscellaneous" not in system
    assert "use filesystem.find with kind=any" not in system.casefold()
    assert "Use tools_search if a required public action is not exposed." not in system
    assert "Do not rediscover the root" in system


def _classification_state():
    state = _organization_state()
    state.instruction = "Move code files into the 'Code' folder and everything else under 'Other'."
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": "/home/user/Desktop/main.py", "kind": "file"},
        {"path": "/home/user/Desktop/notes.txt", "kind": "file"},
        {"path": "/home/user/Desktop/Code", "kind": "directory"},
        {"path": "/home/user/Desktop/Other", "kind": "directory"},
    ]
    return state


def _independent_check(state, selected, *, decided="/home/user/Desktop/Code", disposition="move", sufficient=True, screenshot=None, quote=""):
    client = Mock()
    client.propose.return_value = {
        "tool": "organization__classification_verdict",
        "arguments_raw": json.dumps({
            "observed_type": "source file or observed document", "evidence_quote": quote,
            "disposition": disposition if sufficient else "insufficient_evidence", "destination_directory": decided,
            "reason": "Observed content and instruction agree.",
        }),
    }
    executor = Mock()
    executor.execute.return_value = {"executed": True, "result": {"verification_passed": True}}
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), executor, model_client=client)
    event = agent.execute_proposal(state, {
        "tool": VERIFY_TOOL,
        "arguments_raw": json.dumps({
            "path": state.filesystem_organization_current_entry()["path"],
            "destination_directory": selected, "disposition": "retain" if disposition == "retain" else "move",
            "evidence": "planner-secret: proposed classification",
        }),
        "_model_visible_tools": agent.tools(state),
    }, screenshot=screenshot)
    return agent, event, client, executor


def test_independent_disagreement_does_not_move_skip_or_advance():
    state = _classification_state()
    agent, event, client, executor = _independent_check(state, "/home/user/Desktop/Other")
    assert event.executed, event.error
    assert event.result["passed"] is False
    assert state.filesystem_organization_current_entry()["path"].endswith("main.py")
    assert {tool["function"]["name"] for tool in agent.tools(state)} == {VERIFY_TOOL}
    executor.execute.assert_not_called()
    assert "planner-secret" not in json.dumps(client.propose.call_args.kwargs["messages"])
    assert client.propose.call_args.kwargs["output_token_budget"] == 512
    verdict_schema = client.propose.call_args.kwargs["tools"][0]["function"]["parameters"]
    assert set(verdict_schema["properties"]) == {
        "observed_type", "evidence_quote", "disposition", "destination_directory", "reason",
    }
    assert verdict_schema["additionalProperties"] is False
    assert not state.filesystem_organization_complete()


@pytest.mark.parametrize("physical_passed", [True, False])
def test_checked_move_advances_only_after_physical_verification(physical_passed):
    state = _classification_state()
    agent, check, _client, executor = _independent_check(state, "/home/user/Desktop/Code")
    assert check.result["passed"] is True, check.error
    tools = agent.tools(state)
    assert "organization__skip_current" not in {tool["function"]["name"] for tool in tools}
    adapter = next(tool["function"] for tool in tools if tool["function"]["name"] == "adapter__adapter_call")
    params = adapter["parameters"]["properties"]["payload"]["properties"]["params"]
    assert params["properties"]["destination"]["enum"] == ["/home/user/Desktop/Code/main.py"]
    executor.execute.return_value = {"executed": True, "result": {"verification_passed": physical_passed}}
    moved = agent.execute_proposal(state, {
        "tool": "adapter__adapter_call",
        "arguments_raw": json.dumps({"adapter": "os", "action": "filesystem.rename", "payload": {"params": {
            "source": "/home/user/Desktop/main.py", "destination": "/home/user/Desktop/Code/main.py",
        }}}), "_model_visible_tools": tools,
    })
    assert moved.executed, moved.error
    expected = "notes.txt" if physical_passed else "main.py"
    assert state.filesystem_organization_current_entry()["path"].endswith(expected)
    if not physical_passed:
        assert {tool["function"]["name"] for tool in agent.tools(state)} == {"fail_task"}


def test_exhaustive_organization_cannot_retain_unplaced_source_even_if_checker_agrees():
    state = _classification_state()
    agent, event, _client, _executor = _independent_check(
        state, "/home/user/Desktop", decided="/home/user/Desktop", disposition="retain",
    )
    assert event.executed, event.error
    assert event.result["passed"] is False
    assert "organization__skip_current" not in {tool["function"]["name"] for tool in agent.tools(state)}
    skipped = agent.execute_proposal(state, {"tool": "organization__skip_current", "arguments_raw": json.dumps({
        "path": "/home/user/Desktop/main.py", "reason": "already classified; should move, not skip",
    })})
    assert not skipped.executed
    assert state.filesystem_organization_current_entry()["path"].endswith("main.py")


def test_already_correct_location_exposes_skip_only_after_independent_check():
    state = _classification_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"][0]["path"] = "/home/user/Desktop/Code/main.py"
    agent, event, _client, _executor = _independent_check(
        state, "/home/user/Desktop/Code", decided="/home/user/Desktop/Code", disposition="retain",
    )
    assert event.result["passed"] is True, event.error
    tools = agent.tools(state)
    assert {tool["function"]["name"] for tool in tools} == {"organization__skip_current"}
    skipped = agent.execute_proposal(state, {"tool": "organization__skip_current", "arguments_raw": json.dumps({
        "path": "/home/user/Desktop/Code/main.py", "reason": "already in the independently verified destination",
    }), "_model_visible_tools": tools})
    assert skipped.executed, skipped.error
    assert state.filesystem_organization_current_entry()["path"].endswith("notes.txt")


def test_target_directories_are_not_sources_and_exclusion_prompt_survives_binding():
    state = _classification_state()
    assert state.filesystem_organization_pending_entries() == ["/home/user/Desktop/main.py", "/home/user/Desktop/notes.txt"]
    assert set(state.filesystem_organization_destinations()) == {"/home/user/Desktop/Code", "/home/user/Desktop/Other"}
    fresh = RuntimeState(task_id="synthetic", domain="multi_apps", instruction=state.instruction)
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), _NoopExecutor())
    system = agent._messages(fresh, b"png", tools=build_tools(
        "multi_apps", ["adapter.call"], include_gui=False, include_control_tools=True, strict_generic=True,
    ))[0]["content"]
    assert "Exclude the destination category folders" in system


def test_open_is_not_read_and_visual_check_keeps_screenshot_and_blocks_insufficient_content():
    state = _classification_state()
    state.events[0].result["context_hint"]["downstream_context"]["matches"][0] = {
        "path": "/home/user/Desktop/opaque.ppt", "kind": "file",
    }
    state.events.append(ExecutionEvent(
        step=2, timestamp_utc="2026-01-01T00:00:01Z", executed=True,
        proposed={"kind": "adapter", "action": "adapter.call", "arguments": {
            "adapter": "os", "action": "desktop.open_path", "payload": {"params": {"path": "/home/user/Desktop/opaque.ppt"}},
        }}, result={"context_hint": {"path": "/home/user/Desktop/opaque.ppt", "opened": True}},
    ))
    assert "/home/user/Desktop/opaque.ppt" not in state.filesystem_organization_read_paths()
    agent, event, client, executor = _independent_check(
        state, "/home/user/Desktop/Code", disposition="insufficient_evidence", sufficient=False, screenshot=b"test-image",
    )
    assert event.executed, event.error
    assert not event.result["passed"]
    content = client.propose.call_args.kwargs["messages"][1]["content"]
    assert any(part["type"] == "image_url" for part in content)
    tools = agent.tools(state)
    assert VERIFY_TOOL in {tool["function"]["name"] for tool in tools}
    assert "organization__skip_current" not in {tool["function"]["name"] for tool in tools}
    messages = agent._messages(state, b"test-image", tools=tools)
    assert any(part["type"] == "image_url" for part in messages[-1]["content"])
    assert "opaque.ppt" in json.dumps(messages)
    executor.execute.assert_not_called()


def test_checker_transport_failure_does_not_grant_move_or_skip():
    state = _classification_state()
    client = Mock()
    client.propose.side_effect = RuntimeError("synthetic checker unavailable")
    executor = Mock()
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), executor, model_client=client)
    event = agent.execute_proposal(state, {"tool": VERIFY_TOOL, "arguments_raw": json.dumps({
        "path": "/home/user/Desktop/main.py", "disposition": "move",
        "destination_directory": "/home/user/Desktop/Code", "evidence": "code source",
    }), "_model_visible_tools": agent.tools(state)})
    assert not event.executed
    assert state.filesystem_organization_check() is None
    assert {tool["function"]["name"] for tool in agent.tools(state)} == {VERIFY_TOOL}
    executor.execute.assert_not_called()


def test_visual_observation_can_retry_after_insufficient_evidence():
    state = _classification_state()
    source = "/home/user/Desktop/opaque.ppt"
    state.events[0].result["context_hint"]["downstream_context"]["matches"][0] = {"path": source, "kind": "file"}
    arguments = {"adapter": "os", "action": "desktop.open_path", "payload": {"params": {"path": source}}}
    state.events.append(ExecutionEvent(
        step=2, timestamp_utc="2026-01-01T00:00:01Z", executed=True,
        proposed={"kind": "adapter", "action": "adapter.call", "arguments": arguments},
        result={"context_hint": {"path": source, "opened": True}},
    ))
    agent, checked, _client, executor = _independent_check(
        state, "/home/user/Desktop/Code", disposition="insufficient_evidence", sufficient=False, screenshot=b"png",
    )
    assert checked.result["passed"] is False
    executor.execute.return_value = {"executed": True, "result": {"context_hint": {"path": source, "opened": True}}}
    event = agent.execute_proposal(state, {
        "tool": "adapter__adapter_call", "arguments_raw": json.dumps(arguments), "_model_visible_tools": agent.tools(state),
    })
    assert event.executed, event.error
    assert state.filesystem_organization_current_entry()["path"] == source
    assert state.filesystem_organization_check() is None


def test_new_observation_invalidates_a_previous_classification_check():
    state = _classification_state()
    _checked(state, "/home/user/Desktop/main.py", "/home/user/Desktop/Code")
    state.events.append(ExecutionEvent(
        step=3, timestamp_utc="2026-01-01T00:00:02Z", executed=True,
        proposed={"kind": "adapter", "action": "adapter.call", "arguments": {
            "adapter": "os", "action": "file.read_text", "payload": {"params": {"path": "/home/user/Desktop/main.py"}},
        }}, result={"text": "new content"},
    ))
    assert state.filesystem_organization_check() is None
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), _NoopExecutor())
    assert {tool["function"]["name"] for tool in agent.tools(state)} == {VERIFY_TOOL}


@pytest.mark.parametrize("quote, passed", [("print('hello')", True), ("invented research methods", False), ("", False)])
def test_independent_check_requires_observed_verbatim_evidence(quote, passed):
    state = _classification_state()
    state.events.append(ExecutionEvent(
        step=2, timestamp_utc="2026-01-01T00:00:01Z", executed=True,
        proposed={"kind": "adapter", "action": "adapter.call", "arguments": {
            "adapter": "vs_code", "action": "file.read_text", "payload": {"params": {"path": "/home/user/Desktop/main.py"}},
        }}, result={"context_hint": {"text": "print('hello')"}},
    ))
    _agent, event, _client, executor = _independent_check(state, "/home/user/Desktop/Code", quote=quote)
    assert event.executed, event.error
    assert event.result["passed"] is passed
    assert event.result["quotes_verified"] is passed
    executor.execute.assert_not_called()


@pytest.mark.parametrize("quote, passed, physical_passed", [
    ("main.py", True, True), ("main.py", True, False), ("main.py, utils.py", False, True),
])
def test_directory_inspection_is_recursive_current_source_only_and_preserves_inventory(quote, passed, physical_passed):
    state = _organization_state()
    original = state.filesystem_observation_state()["observed_entries"]
    state.filesystem_organization_inventory = original.copy()
    executor = Mock()
    nested = [
        {"path": "/home/user/Desktop/project/subfolder/main.py", "name": "main.py", "kind": "file"},
        {"path": "/home/user/Desktop/project/subfolder/utils.py", "name": "utils.py", "kind": "file"},
    ]
    executor.execute.return_value = {
        "executed": True, "organization_inventory": nested,
        "result": {"context_hint": {"downstream_context": {"matches": nested, "truncated": False}}},
    }
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), executor)
    tools = agent.tools(state)
    reader = next(tool["function"] for tool in tools if tool["function"]["name"] == "adapter__adapter_call")
    assert reader["parameters"]["x-allowed-routes"] == [{"adapter": "os", "action": "filesystem.find"}]
    params = reader["parameters"]["properties"]["payload"]["properties"]["params"]
    assert params["properties"]["roots"]["items"]["enum"] == ["/home/user/Desktop/project"]
    assert params["properties"]["recursive"]["enum"] == [True]
    event = agent.execute_proposal(state, {
        "tool": "adapter__adapter_call", "arguments_raw": json.dumps({
            "adapter": "os", "action": "filesystem.find", "payload": {"params": {
                "roots": ["/home/user/Desktop/project"], "name_patterns": ["*"],
                "kind": "any", "recursive": True, "max_depth": 3, "max_results": 200,
            }},
        }), "_model_visible_tools": tools,
    })
    assert event.executed, event.error
    assert state.filesystem_organization_inventory == original
    assert state.filesystem_observation_state()["observed_entries"] == original
    assert state.filesystem_organization_current_entry()["path"] == "/home/user/Desktop/project"
    assert "main.py" in json.dumps(state.filesystem_organization_evidence())
    assert {tool["function"]["name"] for tool in agent.tools(state)} == {VERIFY_TOOL}
    _agent, check, _client, _executor = _independent_check(state, "/home/user/Desktop/Code", quote=quote)
    assert check.result["passed"] is passed, check.error
    assert "ONE exact name or path" in _client.propose.call_args.kwargs["messages"][0]["content"]
    assert state.filesystem_organization_current_entry()["path"] == "/home/user/Desktop/project"
    if passed:
        _executor.execute.return_value = {"executed": True, "result": {"verification_passed": physical_passed}}
        tools = _agent.tools(state)
        moved = _agent.execute_proposal(state, {
            "tool": "adapter__adapter_call", "arguments_raw": json.dumps({
                "adapter": "os", "action": "filesystem.rename", "payload": {"params": {
                    "source": "/home/user/Desktop/project", "destination": "/home/user/Desktop/Code/project",
                }},
            }), "_model_visible_tools": tools,
        })
        assert moved.executed, moved.error
        status = state.filesystem_organization_progress()["objects"]["/home/user/Desktop/project"]
        assert status["classified"] is physical_passed and status["moved"] is physical_passed
        assert (state.filesystem_organization_current_entry()["path"] != "/home/user/Desktop/project") is physical_passed


def test_quote_line_wrapping_is_accepted_but_summary_is_not():
    state = _classification_state()
    state.events.append(ExecutionEvent(
        step=2, timestamp_utc="2026-01-01T00:00:01Z", executed=True,
        proposed={"kind": "adapter", "action": "adapter.call", "arguments": {
            "adapter": "vs_code", "action": "file.read_text", "payload": {"params": {"path": "/home/user/Desktop/main.py"}},
        }}, result={"text": "A factual\n\t source excerpt with all words."},
    ))
    _agent, check, _client, _executor = _independent_check(state, "/home/user/Desktop/Code", quote="A factual source excerpt")
    assert check.result["passed"] is True
    state.events.pop()  # A fresh verification phase, not a post-pass mutation lease.
    _agent, check, _client, _executor = _independent_check(state, "/home/user/Desktop/Code", quote="A factual ... with all words")
    assert check.result["passed"] is False


def test_top_level_directory_screenshot_alone_cannot_grant_classification():
    state = _organization_state()
    state.events.append(ExecutionEvent(
        step=2, timestamp_utc="2026-01-01T00:00:01Z", executed=True,
        proposed={"kind": "adapter", "action": "adapter.call", "arguments": {
            "adapter": "os", "action": "desktop.open_path", "payload": {"params": {"path": "/home/user/Desktop/project"}},
        }}, result={"opened": True},
    ))
    _agent, event, client, executor = _independent_check(state, "/home/user/Desktop/Code", screenshot=b"png")
    assert not event.executed
    assert state.filesystem_organization_evidence() is None
    assert state.filesystem_organization_current_entry()["path"] == "/home/user/Desktop/project"
    client.propose.assert_not_called()
    executor.execute.assert_not_called()


def _typed_organization_state(path, text=None, complete=True):
    state = _organization_state()
    state.instruction = "Organize my files and folders. Place scholarly articles in 'Reading', software projects in 'Code', and everything else under 'Archive'."
    state.events[0].result["context_hint"]["downstream_context"]["matches"] = [
        {"path": path, "kind": "file"},
        *({"path": f"/home/user/Desktop/{name}", "kind": "directory"} for name in ("Reading", "Code", "Archive")),
    ]
    if text is not None:
        state.events.append(ExecutionEvent(
            step=2, timestamp_utc="2026-01-01T00:00:01Z", executed=True,
            proposed={"kind": "adapter", "action": "adapter.call", "arguments": {
                "adapter": "os", "action": "pdf.extract_text_batch", "payload": {"params": {"input_pattern": path}},
            }}, result={"context_hint": {"downstream_context": {
                "files": [{"path": path, "text": text}], "source_has_more": not complete, "all_text_visible": True,
            }}},
        ))
    return state


def test_presentation_cannot_satisfy_scholarly_article_or_software_project_criterion():
    state = _typed_organization_state("/home/user/Desktop/lesson.ppt")
    current = state.filesystem_organization_current_entry()
    assert state.filesystem_organization_candidates(current) == ["/home/user/Desktop/Archive"]
    _agent, rejected, client, executor = _independent_check(state, "/home/user/Desktop/Reading", screenshot=b"png")
    assert not rejected.executed
    client.propose.assert_not_called()
    executor.execute.assert_not_called()
    assert state.filesystem_organization_current_entry() == current


@pytest.mark.parametrize("text, complete, reading_allowed", [
    ("Overview\nPopulation statistics summarized from other studies.\nPublic information.", True, False),
    ("arXiv:1234.5678\nAbstract\nWe present an original experiment.", True, True),
    ("Journal of Examples\nA scholarly letter with authors and findings.", True, True),
    ("Only a partial observation; later pages have not been read.", False, True),
])
def test_primary_article_evidence_is_not_replaced_by_research_topic(text, complete, reading_allowed):
    state = _typed_organization_state("/home/user/Desktop/material.pdf", text, complete)
    candidates = state.filesystem_organization_candidates(state.filesystem_organization_current_entry())
    assert ("/home/user/Desktop/Reading" in candidates) is reading_allowed
    assert "/home/user/Desktop/Code" not in candidates
    assert "/home/user/Desktop/Archive" in candidates


def test_checker_schema_retry_is_bounded_and_preserves_diagnostic_without_planner_bias():
    state = _classification_state()
    failure = StructuredToolProtocolError(
        "undeclared localized key", response_snapshot={"raw_marker": "untrusted-checker-draft"},
        schema_hints=("remove undeclared fields",),
    )
    success = {"tool": "organization__classification_verdict", "arguments_raw": json.dumps({
        "observed_type": "source code", "evidence_quote": "", "disposition": "move",
        "destination_directory": "/home/user/Desktop/Code", "reason": "A code source.",
    })}
    client = Mock()
    client.propose.side_effect = [failure, success]
    executor = Mock()
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), executor, model_client=client)
    event = agent.execute_proposal(state, {"tool": VERIFY_TOOL, "arguments_raw": json.dumps({
        "path": "/home/user/Desktop/main.py", "disposition": "move", "destination_directory": "/home/user/Desktop/Code", "evidence": "planner-secret",
    }), "_model_visible_tools": agent.tools(state)})
    assert event.result["passed"] is True, event.error
    assert client.propose.call_count == 2
    assert event.result["checker_protocol_retries"] == 1
    assert event.proposed["checker_diagnostics"][0]["response"]["raw_marker"] == "untrusted-checker-draft"
    assert "planner-secret" not in json.dumps(client.propose.call_args.kwargs["messages"])
    assert "untrusted-checker-draft" not in json.dumps(client.propose.call_args.kwargs["messages"])
    assert "untrusted-checker-draft" not in json.dumps(state.filesystem_organization_model_context())
    executor.execute.assert_not_called()


def test_checker_repeated_schema_failure_remains_closed_and_preserves_raw_trace():
    state = _classification_state()
    client = Mock()
    client.propose.side_effect = StructuredToolProtocolError(
        "undeclared key", response_snapshot={"raw_marker": "failed-checker-draft"},
        schema_hints=("remove undeclared fields",),
    )
    executor = Mock()
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), executor, model_client=client)
    event = agent.execute_proposal(state, {"tool": VERIFY_TOOL, "arguments_raw": json.dumps({
        "path": "/home/user/Desktop/main.py", "disposition": "move", "destination_directory": "/home/user/Desktop/Code", "evidence": "code source",
    }), "_model_visible_tools": agent.tools(state)})
    assert not event.executed
    assert client.propose.call_count == 2
    assert event.proposed["checker_failure_trace"]["response"]["raw_marker"] == "failed-checker-draft"
    assert event.error["checker_schema_hints"] == ["remove undeclared fields"]
    assert "failed-checker-draft" not in json.dumps(state.filesystem_organization_model_context())
    assert state.filesystem_organization_check() is None
    assert state.filesystem_organization_current_entry()["path"].endswith("main.py")
    executor.execute.assert_not_called()


@pytest.mark.parametrize("corrected_quote, passed", [("Burgers", True), ('[["Location", "Burgers"]]', False)])
def test_checker_table_quote_correction_is_bounded_and_never_joins_cells(corrected_quote, passed):
    state = _typed_organization_state("/home/user/Desktop/data.xlsx")
    state.events.append(ExecutionEvent(
        step=2, timestamp_utc="2026-01-01T00:00:01Z", executed=True,
        proposed={"kind": "adapter", "action": "adapter.call", "arguments": {
            "adapter": "libreoffice_calc", "action": "workbook.read_file",
            "payload": {"params": {"path": "/home/user/Desktop/data.xlsx"}},
        }}, result={"context_hint": {"sheets": [{"display_text": [["Location", "Burgers"]]}]}},
    ))
    def verdict(quote):
        return {"tool": "organization__classification_verdict", "arguments_raw": json.dumps({
            "observed_type": "spreadsheet", "evidence_quote": quote, "disposition": "move",
            "destination_directory": "/home/user/Desktop/Archive", "reason": "Observed tabular data.",
        })}
    client = Mock()
    draft = {**verdict('[["Location", "Burgers"]]'), "id": "bad-draft-marker"}
    client.propose.side_effect = [draft, verdict(corrected_quote)]
    executor = Mock()
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused", include_gui=False), executor, model_client=client)
    event = agent.execute_proposal(state, {"tool": VERIFY_TOOL, "arguments_raw": json.dumps({
        "path": "/home/user/Desktop/data.xlsx", "disposition": "move",
        "destination_directory": "/home/user/Desktop/Archive", "evidence": "planner-secret",
    }), "_model_visible_tools": agent.tools(state)})
    assert event.result["passed"] is passed, event.error
    assert client.propose.call_count == 2
    assert event.proposed["checker_diagnostics"][0]["response"]["id"] == "bad-draft-marker"
    messages = json.dumps(client.propose.call_args.kwargs["messages"])
    assert "planner-secret" not in messages and "bad-draft-marker" not in messages
    assert "bad-draft-marker" not in json.dumps(state.filesystem_organization_model_context())
    assert state.filesystem_organization_current_entry()["path"] == "/home/user/Desktop/data.xlsx"
    executor.execute.assert_not_called()
