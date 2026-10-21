from __future__ import annotations

import json

from integrations.lite_agent import batch_table_semantics
from integrations.lite_agent import adapter_results
from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


class _NoAdapterExecutor:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("these surface tests must not execute an Adapter")


OPEN_TARGET_INSTRUCTION = (
    "For each source PDF, extract the records and fill the spreadsheet already "
    "open in Calc."
)


def _agent(*, include_gui: bool = False) -> LiteAgent:
    return LiteAgent(
        LiteAgentConfig(
            base_url="http://unused/v1",
            include_gui=include_gui,
            top_k_actions=7,
        ),
        _NoAdapterExecutor(),  # type: ignore[arg-type]
        gui_executor=(lambda _arguments: {}) if include_gui else None,
    )


def _state(
    *,
    instruction: str = OPEN_TARGET_INSTRUCTION,
    task_id: str = "synthetic-task",
) -> RuntimeState:
    return RuntimeState(task_id=task_id, domain="multi_apps", instruction=instruction)


def _append_batch_result(
    state: RuntimeState,
    *,
    count: int = 3,
    step: int = 1,
    input_pattern: str = "*.pdf",
    max_chars_per_file: int | None = None,
    truncated: bool = False,
) -> None:
    arguments: dict[str, object] = {"input_pattern": input_pattern}
    if max_chars_per_file is not None:
        arguments["max_chars_per_file"] = max_chars_per_file

    files = [
        {
            "path": f"/tmp/source-{index}.pdf",
            "text": "record " * (900 if truncated else 1),
            **(
                {
                    "extracted_chars": 8_000,
                    "truncated": True,
                }
                if truncated
                else {}
            ),
        }
        for index in range(count)
    ]
    state.events.append(
        ExecutionEvent(
            step=step,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__pdf_extract_text_batch",
                "action": "pdf.extract_text_batch",
                "arguments": arguments,
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "action": "pdf.extract_text_batch",
                    "result": {
                        "matched_count": count,
                        "files": files,
                    },
                }
            },
        )
    )


def _append_window_batch_result(
    state: RuntimeState,
    *,
    step: int,
    start_char: int,
    end_char: int,
    total_chars: int,
    source_truncated: bool,
) -> None:
    text = "source-window-" * max(1, end_char - start_char)
    text = text[: end_char - start_char]
    state.events.append(
        ExecutionEvent(
            step=step,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__pdf_extract_text_batch",
                "action": "pdf.extract_text_batch",
                "arguments": {
                    "input_pattern": "source-0.pdf",
                    "start_char": start_char,
                    "max_chars_per_file": end_char - start_char,
                },
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "action": "pdf.extract_text_batch",
                    "result": {
                        "matched_count": 1,
                        "files": [
                            {
                                "path": "/tmp/source-0.pdf",
                                "text": text,
                                "extracted_chars": total_chars,
                                "source_start_char": start_char,
                                "source_end_char": end_char,
                                "source_total_chars": total_chars,
                                "next_start_char": end_char
                                if source_truncated
                                else None,
                                "source_truncated": source_truncated,
                                "offset_basis": "extracted_text",
                            }
                        ],
                    },
                }
            },
        )
    )


def _append_inspect_result(state: RuntimeState, *, step: int = 2) -> None:
    state.events.append(
        ExecutionEvent(
            step=step,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__spreadsheet_inspect_current",
                "action": "spreadsheet.inspect_current",
                "arguments": {},
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "action": "spreadsheet.inspect_current",
                    "result": {
                        "adapter": "libreoffice_calc",
                        "action": "workbook.inspect",
                        "response": {
                            "status": "ok",
                            "result": {
                                "title": "supported.ods",
                                "active_sheet": "Sheet1",
                                "sheets": [{"name": "Sheet1"}],
                            },
                        },
                    },
                }
            },
        )
    )


def _append_pdf_table_result(
    state: RuntimeState, *, input_path: str, step: int
) -> None:
    state.events.append(
        ExecutionEvent(
            step=step,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__pdf_tables_inspect",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "pdf.tables.inspect",
                    "payload": {"params": {"input_path": input_path, "page": 1}},
                },
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "result": {
                        "adapter": "os",
                        "action": "pdf.tables.inspect",
                        "response": {
                            "status": "ok",
                            "result": {
                                "input_path": input_path,
                                "table_count": 1,
                                "table_index": 0,
                                "row_count": 4,
                                "column_count": 3,
                                "rows": [["Year", "HKU", "Other"], ["2019", "25", "7"]],
                            },
                        },
                    },
                }
            },
        )
    )


def _append_failed_inspect(state: RuntimeState) -> None:
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__spreadsheet_inspect_current",
                "action": "spreadsheet.inspect_current",
                "arguments": {},
            },
            executed=False,
            error={"type": "NO_CALC_DOCUMENT"},
        )
    )


def _append_failed_batch(state: RuntimeState) -> None:
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__pdf_extract_text_batch",
                "action": "pdf.extract_text_batch",
                "arguments": {"input_pattern": "*.pdf"},
            },
            executed=False,
            error={"type": "NO_MATCHES"},
        )
    )


def _append_failed_write(state: RuntimeState, *, step: int = 3) -> None:
    state.events.append(
        ExecutionEvent(
            step=step,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__spreadsheet_write_range",
                "action": "spreadsheet.write_range",
                "arguments": {
                    "sheet": "Sheet1",
                    "range": "A1:B2",
                    "values": [["x", "y"], ["z", "w"]],
                },
            },
            executed=False,
            error={"type": "INVALID_ARGUMENT"},
        )
    )


def _append_failed_read(
    state: RuntimeState,
    *,
    error: dict[str, object],
    step: int = 3,
) -> None:
    state.events.append(
        ExecutionEvent(
            step=step,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__spreadsheet_read_file",
                "action": "spreadsheet.read_file",
                "arguments": {
                    "path": "/tmp/open.xlsx",
                    "sheet": "Sheet1",
                    "range": "A1:I10",
                },
            },
            executed=False,
            error=error,
        )
    )


def _append_successful_read(
    state: RuntimeState,
    *,
    step: int,
    target_range: str = "A1:I10",
) -> None:
    state.events.append(
        ExecutionEvent(
            step=step,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__spreadsheet_read_file",
                "action": "spreadsheet.read_file",
                "arguments": {
                    "path": "/tmp/open.xlsx",
                    "sheet": "Sheet1",
                    "range": target_range,
                },
            },
            executed=True,
            result={"adapter_response": {"status": "ok", "result": {}}},
        )
    )


def _append_header_only_create(state: RuntimeState) -> None:
    state.events.append(
        ExecutionEvent(
            step=3,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__spreadsheet_create_workbook",
                "action": "spreadsheet.create_workbook",
                "arguments": {
                    "output_path": "/tmp/result.ods",
                    "headers": ["University"],
                },
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "action": "spreadsheet.create_workbook",
                    "result": {
                        "sheet": "Sheet1",
                        "table_state": "header_only",
                    },
                }
            },
        )
    )


def test_truncated_batch_keeps_observed_reader_before_bounded_consumers() -> None:
    state = _state()
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__pdf_extract_text_batch",
                "action": "pdf.extract_text_batch",
                "arguments": {"input_pattern": "*.pdf"},
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "action": "pdf.extract_text_batch",
                    "result": {
                        "matched_count": 2,
                        "files": [
                            {
                                "path": f"/tmp/source-{index}.pdf",
                                "text": "record " * 900,
                                "extracted_chars": 8_000,
                                "truncated": True,
                            }
                            for index in range(2)
                        ],
                    },
                }
            },
        )
    )
    _append_inspect_result(state)

    actions = batch_table_semantics.pending_consumer_actions(state, [])

    assert actions[0] == "pdf.extract_text_batch"
    assert actions[1:] == batch_table_semantics.CONSUMER_ACTIONS


def test_source_continuation_preserves_target_probe_and_moves_to_consumers() -> None:
    state = _state()
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__pdf_extract_text_batch",
                "action": "pdf.extract_text_batch",
                "arguments": {"input_pattern": "*.pdf"},
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "action": "pdf.extract_text_batch",
                    "result": {
                        "matched_count": 1,
                        "files": [
                            {
                                "path": "/tmp/source.pdf",
                                "text": "record " * 900,
                                "extracted_chars": 8_000,
                                "truncated": True,
                            }
                        ],
                    },
                }
            },
        )
    )
    _append_inspect_result(state)
    assert batch_table_semantics.inspection_pending(state) is False

    state.events.append(
        ExecutionEvent(
            step=3,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__pdf_extract_text_batch",
                "action": "pdf.extract_text_batch",
                "arguments": {"input_pattern": "source.pdf"},
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "action": "pdf.extract_text_batch",
                    "result": {
                        "matched_count": 1,
                        "files": [
                            {
                                "path": "/tmp/source.pdf",
                                "text": "complete record",
                                "extracted_chars": 15,
                                "truncated": False,
                            }
                        ],
                    },
                }
            },
        )
    )

    assert batch_table_semantics.batch_continuation_action(state) is None


def test_completed_fields_hide_only_batch_routes() -> None:
    state = _state(
        instruction=(
            "Extract the name, e-mail, and affiliation of the first author from "
            "each paper and organize them in an Excel table."
        )
    )
    _append_batch_result(state, count=1, step=1, truncated=True)
    files = state.events[0].result["adapter_response"]["result"]["files"]
    files[0]["text"] = "First Author\nExample University\nfirst@example.edu"
    assert batch_table_semantics.requested_fields_complete(state)
    assert not batch_table_semantics.batch_route_allowed_after_completion(
        state, "pdf.extract_text_batch"
    )
    assert batch_table_semantics.batch_route_allowed_after_completion(
        state, "workbook.create_new"
    )
    assert not batch_table_semantics.batch_route_allowed_after_completion(
        state, "filesystem.find"
    )


def test_downstream_batch_routes_require_a_successful_source_observation() -> None:
    """A search hit cannot advance the workflow past the PDF producer."""
    state = _state()

    assert batch_table_semantics.batch_route_allowed_after_completion(
        state, "pdf.extract_text_batch"
    )
    assert not batch_table_semantics.batch_route_allowed_after_completion(
        state, "pdf.tables.inspect"
    )
    assert not batch_table_semantics.batch_route_allowed_after_completion(
        state, "workbook.inspect"
    )
    assert not batch_table_semantics.structured_pdf_table_observation_pending(state)


def test_search_result_cannot_replace_initial_pdf_batch_reader() -> None:
    """Common tool constraints retain only the producer before its first success."""
    state = _state()
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "catalog",
                "tool": "tools_search",
                "action": "tools_search",
                "arguments": {"query": "PDF extraction and PDF table inspection"},
            },
            executed=True,
            result={
                "matches": [
                    {
                        "action": "adapter.call",
                        "adapter": "os",
                        "downstream_action": "pdf.extract_text_batch",
                    },
                    {
                        "action": "adapter.call",
                        "adapter": "os",
                        "downstream_action": "pdf.tables.inspect",
                    },
                ],
            },
        )
    )
    agent = _agent()
    tools = agent._build_tools(
        state.domain,
        ["adapter.call"],
        include_gui=False,
        include_control_tools=True,
        strict_generic=True,
    )
    constrained = agent._apply_common_tool_constraints(tools, state)
    adapter_tool = next(
        tool
        for tool in constrained
        if tool.get("function", {}).get("name") == "adapter__adapter_call"
    )
    parameters = adapter_tool["function"]["parameters"]
    assert parameters["properties"]["action"]["enum"] == [
        "pdf.extract_text_batch"
    ]


def test_found_pdf_table_route_exposes_execution_api_without_search_retry() -> None:
    state = _state(
        instruction=(
            "For each source PDF, extract the rows for each university and fill "
            "the spreadsheet."
        )
    )
    _append_batch_result(state, count=1)
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "catalog",
                "tool": "tools_search",
                "action": "tools_search",
                "arguments": {"query": "pdf.tables.inspect"},
            },
            executed=True,
            result={
                "matches": [
                    {
                        "action": "adapter.call",
                        "adapter": "os",
                        "downstream_action": "pdf.tables.inspect",
                    }
                ]
            },
        )
    )

    tools = _agent().tools(state)
    names = {tool["function"]["name"] for tool in tools}

    assert names == {"adapter__adapter_call"}
    adapter_tool = tools[0]
    assert adapter_tool["function"]["parameters"]["properties"]["action"]["enum"] == [
        "pdf.tables.inspect"
    ]


def test_unsearched_pdf_table_route_exposes_search_only() -> None:
    state = _state(
        instruction=(
            "For each source PDF, extract the rows for each university and fill "
            "the spreadsheet."
        )
    )
    _append_batch_result(state, count=1)
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "catalog",
                "tool": "tools_search",
                "action": "tools_search",
                "arguments": {"query": "pdf.extract_text_batch"},
            },
            executed=True,
            result={
                "matches": [
                    {
                        "action": "adapter.call",
                        "adapter": "os",
                        "downstream_action": "pdf.extract_text_batch",
                    }
                ]
            },
        )
    )

    names = {tool["function"]["name"] for tool in _agent().tools(state)}

    assert names == {"tools_search"}


def test_initial_batch_read_rejects_unobserved_glob_after_multi_file_discovery() -> None:
    state = _state(
        instruction=(
            "Read each source PDF and organize the extracted results in an Excel table."
        )
    )
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__adapter_call",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "filesystem.find",
                    "payload": {
                        "params": {
                            "roots": ["/tmp/source"],
                            "name_patterns": [
                                "source-0.pdf",
                                "source-1.pdf",
                                "source-2.pdf",
                            ],
                        }
                    },
                },
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "result": {
                        "kind": "file",
                        "match_count": 3,
                        "matches": [
                            {"kind": "file", "path": f"/tmp/source-{i}.pdf"}
                            for i in range(3)
                        ],
                    },
                }
            },
        )
    )

    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "os",
            "action": "pdf.extract_text_batch",
            "payload": {
                "params": {
                    "input_pattern": "*.pdf",
                    "cwd_source": "explicit",
                    "cwd_path": "/tmp",
                }
            },
        },
    )

    assert errors
    assert "exact PDF basenames" in errors[0]

    assert batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "os",
            "action": "pdf.extract_text_batch",
            "payload": {
                "params": {
                    "input_pattern": "source-0.pdf",
                    "cwd_source": "explicit",
                    "cwd_path": "/tmp",
                }
            },
        },
    ) == []


def test_exact_discovery_keeps_remaining_pdf_sources_on_batch_stage() -> None:
    state = _state(
        instruction=(
            "Read each source PDF and organize the extracted results in an Excel table."
        )
    )
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__adapter_call",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "filesystem.find",
                    "payload": {
                        "params": {
                            "roots": ["/tmp/source"],
                            "name_patterns": [
                                "source-0.pdf",
                                "source-1.pdf",
                                "source-2.pdf",
                            ],
                        }
                    },
                },
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "result": {
                        "matches": [
                            {"kind": "file", "path": f"/tmp/source-{i}.pdf"}
                            for i in range(3)
                        ]
                    },
                }
            },
        )
    )
    _append_batch_result(state, count=1, input_pattern="source-0.pdf", step=2)

    assert batch_table_semantics.stage_actions(
        state, [batch_table_semantics.CREATE_ACTION]
    ) == ["pdf.extract_text_batch"]


def test_initial_batch_read_requires_discovered_pdf_directory_explicitly() -> None:
    state = _state(
        instruction=(
            "Read each source PDF and organize the extracted results in an Excel table."
        )
    )
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__adapter_call",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "filesystem.find",
                    "payload": {"params": {"roots": ["/home/user"]}},
                },
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "result": {
                        "match_count": 2,
                        "matches": [
                            {"kind": "file", "path": path}
                            for path in (
                                "/home/user/Documents/Fundings/grf/grf19.pdf",
                                "/home/user/Documents/Fundings/grf/grf20.pdf",
                            )
                        ],
                    },
                }
            },
        )
    )

    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "os",
            "action": "pdf.extract_text_batch",
            "payload": {
                "params": {"input_pattern": "grf*.pdf", "cwd_source": "home"}
            },
        },
    )

    assert errors
    assert 'cwd_source="explicit"' in errors[0]
    assert 'cwd_path="/home/user/Documents/Fundings/grf"' in errors[0]

    assert batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "os",
            "action": "pdf.extract_text_batch",
            "payload": {
                "params": {
                    "input_pattern": "grf*.pdf",
                    "cwd_source": "explicit",
                    "cwd_path": "/home/user/Documents/Fundings/grf",
                }
            },
        },
    ) == []


def test_initial_batch_read_allows_single_basename_for_explicit_single_file_request() -> None:
    state = _state(
        instruction="Read the single source PDF and extract its text into a table."
    )
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__adapter_call",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "filesystem.find",
                    "payload": {"params": {"roots": ["/tmp/source"]}},
                },
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "result": {
                        "matches": [
                            {"kind": "file", "path": f"/tmp/source-{i}.pdf"}
                            for i in range(3)
                        ]
                    },
                }
            },
        )
    )

    assert batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "os",
            "action": "pdf.extract_text_batch",
            "payload": {
                "params": {
                    "input_pattern": "source-0.pdf",
                    "cwd_source": "explicit",
                    "cwd_path": "/tmp",
                }
            },
        },
    ) == []


def test_structured_pdf_table_observation_is_required_before_matrix_creation() -> None:
    state = _state(
        instruction=(
            "Read the HKU application and supported counts for each source PDF, "
            "using the university columns and discipline rows, calculate the success "
            "result, and organize the results in a new Excel table."
        )
    )
    assert not batch_table_semantics.structured_pdf_table_observation_pending(state)
    _append_batch_result(state, count=2, truncated=False)

    assert batch_table_semantics.requested_fields_complete(state)
    assert batch_table_semantics.structured_pdf_table_observation_pending(state)
    assert batch_table_semantics.stage_actions(state, ["workbook.create_new"]) == [
        "pdf.tables.inspect"
    ]
    assert not batch_table_semantics.batch_route_allowed_after_completion(
        state, "workbook.create_new"
    )
    assert batch_table_semantics.batch_route_allowed_after_completion(
        state, "pdf.tables.inspect"
    )
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "workbook.create_new",
        {"headers": ["Year", "#Applied"], "rows": [[2019, 25], [2020, 30]]},
    )
    assert errors and "pdf.tables.inspect" in errors[0]

    for index, item in enumerate(state.events[0].result["adapter_response"]["result"]["files"]):
        _append_pdf_table_result(state, input_path=item["path"], step=index + 2)

    assert not batch_table_semantics.structured_pdf_table_observation_pending(state)
    assert batch_table_semantics.batch_route_allowed_after_completion(
        state, "workbook.create_new"
    )
    assert batch_table_semantics.argument_contract_errors(
        state,
        "workbook.create_new",
        {"headers": ["Year", "#Applied"], "rows": [[2019, 25], [2020, 30]]},
    ) == []


def test_non_tabular_pdf_extraction_does_not_require_pdf_table_inspection() -> None:
    state = _state(
        instruction="Extract the title and author from each PDF and save an Excel table."
    )
    _append_batch_result(state, count=1, truncated=False)
    assert not batch_table_semantics.requires_structured_pdf_table_observation(state)
    assert not batch_table_semantics.structured_pdf_table_observation_pending(state)


def test_incomplete_source_lease_survives_a_successful_continuation() -> None:
    state = _state()
    _append_batch_result(state, count=2, step=1, truncated=True)
    _append_inspect_result(state, step=2)
    assert (
        batch_table_semantics.batch_continuation_action(state)
        == "pdf.extract_text_batch"
    )

    _append_batch_result(
        state,
        count=1,
        step=3,
        input_pattern="source-0.pdf",
        max_chars_per_file=20_000,
        truncated=True,
    )

    assert (
        batch_table_semantics.batch_continuation_action(state)
        == "pdf.extract_text_batch"
    )
    actions = batch_table_semantics.pending_consumer_actions(state, [])
    assert actions[0] == "pdf.extract_text_batch"
    assert actions[1:] == batch_table_semantics.CONSUMER_ACTIONS


def test_complete_source_with_context_only_truncation_does_not_replay_batch() -> None:
    state = _state()
    text = "complete-source " * 2_000
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__pdf_extract_text_batch",
                "action": "pdf.extract_text_batch",
                "arguments": {"input_pattern": "*.pdf"},
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "action": "pdf.extract_text_batch",
                    "result": {
                        "matched_count": 1,
                        "files": [
                            {
                                "path": "/tmp/complete.pdf",
                                "source_truncated": False,
                                "extracted_chars": len(text),
                                "returned_chars": len(text),
                                "text": text,
                            }
                        ],
                    },
                }
            },
        )
    )
    _append_inspect_result(state)

    projection = batch_table_semantics._batch_model_projection(state.events[0])
    assert projection is not None
    assert projection["source_has_more"] is False
    assert projection["context_truncated"] is False
    assert projection["context_window_truncated"] is True
    assert batch_table_semantics.batch_continuation_action(state) is None


def test_layout_compacted_complete_source_does_not_replay_batch() -> None:
    state = _state()
    _append_batch_result(state, count=1, step=1, truncated=False)
    item = state.events[0].result["adapter_response"]["result"]["files"][0]
    item.update(
        {
            "extracted_chars": len(item["text"]) + 320,
            "raw_extracted_chars": len(item["text"]) + 1_100,
            "layout_compacted": True,
            "source_truncated": False,
            "truncated": False,
        }
    )
    _append_inspect_result(state)

    projection = batch_table_semantics._batch_model_projection(state.events[0])
    assert projection is not None
    assert projection["source_has_more"] is False
    assert batch_table_semantics.batch_continuation_action(state) is None


def test_context_omitted_complete_source_does_not_schedule_batch_replay() -> None:
    """Model file-count caps are projection loss, not source pagination."""
    state = _state()
    _append_batch_result(state, count=25, step=1, truncated=False)
    _append_inspect_result(state, step=2)

    projection = batch_table_semantics._batch_model_projection(state.events[0])
    assert projection is not None
    assert projection["files_omitted"] == 5
    assert projection["context_files_omitted"] == 5
    assert projection["source_has_more"] is False
    assert projection["context_truncated"] is False
    assert projection["context_window_truncated"] is True
    assert batch_table_semantics.batch_continuation_action(state) is None


def test_complete_source_failed_write_recovery_does_not_replay_producer() -> None:
    """A consumer rejection must not turn projection-only truncation into a reread."""
    state = _state()
    _append_batch_result(state, count=9, step=1, truncated=False)
    _append_inspect_result(state, step=2)
    _append_successful_read(state, step=3, target_range="A1:I10")
    _append_failed_write(state, step=4)

    assert batch_table_semantics.batch_continuation_action(state) is None
    actions = batch_table_semantics.pending_consumer_recovery_actions(state, [])
    assert actions == batch_table_semantics.CONSUMER_ACTIONS


def test_narrow_source_continuation_does_not_shrink_source_cardinality() -> None:
    state = _state()
    _append_batch_result(state, count=3, step=1, truncated=True)
    _append_inspect_result(state, step=2)
    _append_batch_result(
        state,
        count=1,
        step=3,
        input_pattern="source-0.pdf",
        truncated=True,
    )

    assert batch_table_semantics.expected_record_count(state) == 3


def test_source_cursor_progress_keeps_continuation_until_window_is_complete() -> None:
    state = _state()
    _append_window_batch_result(
        state,
        step=1,
        start_char=0,
        end_char=100,
        total_chars=300,
        source_truncated=True,
    )
    _append_inspect_result(state)

    assert batch_table_semantics.batch_continuation_action(state) == (
        "pdf.extract_text_batch"
    )

    _append_window_batch_result(
        state,
        step=3,
        start_char=100,
        end_char=200,
        total_chars=300,
        source_truncated=True,
    )
    assert batch_table_semantics.batch_continuation_action(state) == (
        "pdf.extract_text_batch"
    )

    _append_window_batch_result(
        state,
        step=4,
        start_char=200,
        end_char=300,
        total_chars=300,
        source_truncated=False,
    )
    assert batch_table_semantics.batch_continuation_action(state) is None


def test_repeated_target_probe_does_not_reset_continuation_cap() -> None:
    state = _state()
    _append_batch_result(state, count=2, step=1, truncated=True)
    _append_inspect_result(state, step=2)
    for step, pattern in enumerate(
        ("source-0.pdf", "source-1.pdf", "source-2.pdf"), start=3
    ):
        _append_batch_result(
            state,
            count=1,
            step=step,
            input_pattern=pattern,
            truncated=True,
        )
        _append_inspect_result(state, step=step + 1)

    assert batch_table_semantics.batch_continuation_action(state) is None


def test_incomplete_source_lease_rejects_an_exact_successful_replay() -> None:
    state = _state()
    _append_batch_result(state, count=2, step=1, truncated=True)
    _append_inspect_result(state, step=2)
    _append_batch_result(state, count=2, step=3, truncated=True)

    assert batch_table_semantics.batch_continuation_action(state) is None
    assert batch_table_semantics.pending_consumer_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_incomplete_source_lease_has_a_finite_attempt_cap() -> None:
    state = _state()
    _append_batch_result(state, count=2, step=1, truncated=True)
    _append_inspect_result(state, step=2)
    for step, pattern in enumerate(
        ("source-0.pdf", "source-1.pdf", "source-2.pdf"), start=3
    ):
        _append_batch_result(
            state,
            count=1,
            step=step,
            input_pattern=pattern,
            max_chars_per_file=20_000,
            truncated=True,
        )

    assert batch_table_semantics.batch_continuation_action(state) is None
    assert batch_table_semantics.pending_consumer_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_incomplete_source_lease_stops_after_a_successful_mutation() -> None:
    state = _state()
    _append_batch_result(state, count=2, step=1, truncated=True)
    _append_inspect_result(state, step=2)
    _append_batch_result(
        state,
        count=1,
        step=3,
        input_pattern="source-0.pdf",
        truncated=True,
    )
    state.events.append(
        ExecutionEvent(
            step=4,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__spreadsheet_write_range",
                "action": "spreadsheet.write_range",
                "arguments": {"sheet": "Sheet1", "range": "A1:B2", "values": []},
            },
            executed=True,
            result={"adapter_response": {"status": "ok"}},
        )
    )

    assert batch_table_semantics.batch_continuation_action(state) is None


def test_incomplete_source_lease_stops_after_a_successful_gui_action() -> None:
    state = _state()
    _append_batch_result(state, count=2, step=1, truncated=True)
    _append_inspect_result(state, step=2)
    _append_batch_result(
        state,
        count=1,
        step=3,
        input_pattern="source-0.pdf",
        truncated=True,
    )
    state.events.append(
        ExecutionEvent(
            step=4,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "gui",
                "tool": "gui_action",
                "action": "click",
                "arguments": {"x": 10, "y": 20},
            },
            executed=True,
            result={"status": "ok"},
        )
    )

    assert batch_table_semantics.batch_continuation_action(state) is None
    assert batch_table_semantics.pending_consumer_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_incomplete_source_lease_resolves_wrapped_batch_route() -> None:
    state = _state()
    _append_batch_result(state, count=2, step=1, truncated=True)
    _append_inspect_result(state, step=2)
    _append_batch_result(
        state,
        count=1,
        step=3,
        input_pattern="source-0.pdf",
        truncated=True,
    )
    latest = state.events[-1]
    latest.proposed = {
        "kind": "adapter",
        "tool": "adapter__adapter_call",
        "action": "adapter.call",
        "arguments": {
            "adapter": "os",
            "action": "pdf.extract_text_batch",
            "payload": {"params": {"input_pattern": "source-0.pdf"}},
        },
    }

    assert batch_table_semantics.batch_continuation_action(state) == (
        "pdf.extract_text_batch"
    )


def test_incomplete_source_lease_resolves_wrapped_target_probe() -> None:
    state = _state()
    _append_batch_result(state, count=2, step=1, truncated=True)
    _append_inspect_result(state, step=2)
    state.events[-1].proposed = {
        "kind": "adapter",
        "tool": "adapter__adapter_call",
        "action": "adapter.call",
        "arguments": {
            "adapter": "libreoffice_calc",
            "action": "workbook.inspect",
            "payload": {"params": {}},
        },
    }
    _append_batch_result(
        state,
        count=1,
        step=3,
        input_pattern="source-0.pdf",
        truncated=True,
    )

    assert batch_table_semantics._valid_target_inspection(state) is not None
    assert batch_table_semantics.batch_continuation_action(state) == (
        "pdf.extract_text_batch"
    )


def test_source_continuation_preserves_probe_across_target_read() -> None:
    state = _state()
    _append_batch_result(state, step=1)
    _append_inspect_result(state, step=2)
    state.events.append(
        ExecutionEvent(
            step=3,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__spreadsheet_read_file",
                "action": "spreadsheet.read_file",
                "arguments": {"path": "/tmp/open.xlsx", "sheet": "Sheet1"},
            },
            executed=True,
            result={"adapter_response": {"status": "ok", "result": {}}},
        )
    )
    state.events.append(
        ExecutionEvent(
            step=4,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__pdf_extract_text_batch",
                "action": "pdf.extract_text_batch",
                "arguments": {"input_pattern": "source.pdf"},
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "action": "pdf.extract_text_batch",
                    "result": {
                        "matched_count": 1,
                        "files": [
                            {
                                "path": "/tmp/source.pdf",
                                "text": "complete record",
                                "extracted_chars": 15,
                                "truncated": False,
                            }
                        ],
                    },
                }
            },
        )
    )

    assert batch_table_semantics._valid_target_inspection(state) is not None
    assert batch_table_semantics.inspection_pending(state) is False
    assert batch_table_semantics.pending_consumer_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_source_continuation_does_not_trust_gui_read_named_action() -> None:
    state = _state()
    _append_batch_result(state, step=1)
    _append_inspect_result(state, step=2)
    state.events.append(
        ExecutionEvent(
            step=3,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "gui",
                "tool": "gui_action",
                "action": "window.read",
                "arguments": {"x": 1, "y": 2},
            },
            executed=True,
            result={"status": "ok"},
        )
    )
    _append_batch_result(state, count=1, step=4)

    assert batch_table_semantics._valid_target_inspection(state) is None
    assert batch_table_semantics.inspection_pending(state) is True


def test_source_continuation_resolves_read_only_adapter_call() -> None:
    state = _state()
    _append_batch_result(state, step=1)
    _append_inspect_result(state, step=2)
    state.events.append(
        ExecutionEvent(
            step=3,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__adapter_call",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "libreoffice_calc",
                    "action": "workbook.inspect",
                    "payload": {"params": {}},
                },
            },
            executed=True,
            result={"adapter_response": {"status": "ok", "result": {}}},
        )
    )
    _append_batch_result(state, count=1, step=4)

    assert batch_table_semantics._valid_target_inspection(state) is not None
    assert batch_table_semantics.inspection_pending(state) is False


def test_inspection_before_batch_is_not_reused_as_target_probe() -> None:
    state = _state()
    _append_inspect_result(state, step=1)
    _append_batch_result(state, step=2)

    assert batch_table_semantics.inspection_pending(state) is True


def test_complete_batch_does_not_readd_observed_reader() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)

    actions = batch_table_semantics.pending_consumer_actions(state, [])

    assert actions == batch_table_semantics.CONSUMER_ACTIONS
    assert "pdf.extract_text_batch" not in actions


def test_complete_structured_batch_cannot_abort_before_table_mutation() -> None:
    """Source-complete PDF evidence outranks screenshot/failure narratives."""
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)

    names = {tool["function"]["name"] for tool in _agent(include_gui=True).tools(state)}

    assert "fail_task" not in names
    assert "gui_action" not in names


def test_batch_producer_is_detected_before_any_producer_attempt() -> None:
    state = _state()

    assert batch_table_semantics.pending_producer_actions(state, []) == (
        "pdf.extract_text_batch",
    )


def test_batch_producer_detection_survives_unrelated_failure() -> None:
    state = _state()
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "gui",
                "tool": "gui_action",
                "action": "click",
                "arguments": {"x": "504", "y": "76"},
            },
            executed=False,
            error={"type": "ValidationError"},
        )
    )

    assert batch_table_semantics.pending_producer_actions(state, []) == (
        "pdf.extract_text_batch",
    )


def test_failed_batch_attempt_releases_producer_gate() -> None:
    state = _state()
    _append_failed_batch(state)

    assert batch_table_semantics.pending_producer_actions(state, []) == ()
    names = {tool["function"]["name"] for tool in _agent(include_gui=True).tools(state)}
    assert "tools_search" in names
    assert "propose_done" in names
    assert "fail_task" in names
    assert "gui_action" in names


def test_image_batch_producer_uses_same_detection_helper() -> None:
    state = _state(
        instruction=(
            "For each image, extract the labels and put one record per image in the table."
        )
    )

    assert batch_table_semantics.pending_producer_actions(state, []) == (
        "image.extract_text_batch",
    )


def test_batch_probe_remains_pending_after_unrelated_gui_failure() -> None:
    state = _state()
    _append_batch_result(state)
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "gui",
                "tool": "gui_action",
                "action": "click",
                "arguments": {"x": "504", "y": "76"},
            },
            executed=False,
            error={"type": "ValidationError"},
        )
    )

    assert batch_table_semantics.inspection_pending(state)


def test_failed_batch_probe_releases_discovery_only_gate() -> None:
    state = _state(instruction="For each source PDF, create a new spreadsheet.")
    _append_batch_result(state)
    _append_failed_inspect(state)

    assert not batch_table_semantics.inspection_pending(state)
    names = {tool["function"]["name"] for tool in _agent().tools(state)}
    assert "propose_done" not in names
    assert "fail_task" not in names


def test_recovered_batch_probe_does_not_reopen_gui_recovery() -> None:
    state = _state()
    _append_batch_result(state)
    _append_failed_inspect(state)
    _append_inspect_result(state, step=3)

    names = {tool["function"]["name"] for tool in _agent(include_gui=True).tools(state)}
    assert "gui_action" not in names
    assert "propose_done" not in names


def test_batch_replan_keeps_gui_hidden_after_repeated_gui_block() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    state.events.append(
        ExecutionEvent(
            step=3,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "gui",
                "tool": "gui_action",
                "action": "click",
                "arguments": {"x": "506", "y": "74"},
            },
            executed=False,
            error={
                "type": "RepeatedActionBlocked",
                "blocked_action": "gui_action",
                "argument_signature": "synthetic",
                "error_signature": "RepeatedGUIAction",
                "block_scope": "window",
                "blocked_until_step": 8,
            },
        )
    )

    names = {tool["function"]["name"] for tool in _agent(include_gui=True).tools(state)}
    assert "gui_action" not in names
    assert "tools_search" in names


def test_batch_completion_stays_hidden_until_mutation_and_save() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)

    names = {tool["function"]["name"] for tool in _agent().tools(state)}
    assert "propose_done" not in names

    state.events.extend(
        [
            ExecutionEvent(
                step=3,
                timestamp_utc="2026-08-29T00:00:00Z",
                proposed={
                    "kind": "adapter",
                    "tool": "adapter__adapter_call",
                    "action": "adapter.call",
                    "arguments": {
                        "adapter": "libreoffice_calc",
                        "action": "range.write",
                        "payload": {"params": {}},
                    },
                },
                executed=True,
                result={"adapter_response": {"status": "ok", "result": {}}},
            ),
            ExecutionEvent(
                step=4,
                timestamp_utc="2026-08-29T00:00:00Z",
                proposed={
                    "kind": "adapter",
                    "tool": "adapter__adapter_call",
                    "action": "adapter.call",
                    "arguments": {
                        "adapter": "libreoffice_calc",
                        "action": "workbook.save",
                        "payload": {"params": {}},
                    },
                },
                executed=True,
                result={"adapter_response": {"status": "ok", "result": {}}},
            ),
        ]
    )
    assert batch_table_semantics.mutation_and_save_complete(state)


def test_recoverable_failed_consumer_write_is_classified_for_recovery() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_write(state)

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_failed_consumer_write_precedes_incomplete_source_continuation() -> None:
    """A write contract error must not make the source reader the next attractor."""
    state = _state()
    _append_batch_result(state, truncated=True)
    _append_inspect_result(state)
    _append_failed_write(state)

    actions = batch_table_semantics.pending_consumer_recovery_actions(state, [])
    assert actions[: len(batch_table_semantics.CONSUMER_ACTIONS)] == (
        batch_table_semantics.CONSUMER_ACTIONS
    )
    assert actions[-1] == "pdf.extract_text_batch"


def test_nested_downstream_range_error_is_recoverable() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_write(state)
    state.events[-1].error = {
        "status": "error",
        "error": {
            "code": "DOWNSTREAM_FAILED",
            "details": {
                "response": {
                    "status": "error",
                    "error": {
                        "code": "RANGE_INVALID",
                        "message": "typed matrix dimensions do not match target",
                    },
                }
            },
        },
    }

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_partial_commit_write_error_releases_bounded_surface() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_write(state)
    state.events[-1].error = {
        "status": "error",
        "committed": True,
        "error": {"code": "RANGE_INVALID"},
    }

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == ()


def test_write_io_error_releases_bounded_surface() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_write(state)
    state.events[-1].error = {
        "status": "error",
        "error": {"code": "SPREADSHEET_PATH_NOT_FOUND"},
    }

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == ()


def test_duplicate_read_is_classified_for_consumer_recovery() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_read(
        state,
        error={
            "type": "ValueError",
            "detail": "identical successful action already executed at step 3; inspect state or choose a different action",
        },
    )

    actions = batch_table_semantics.pending_consumer_recovery_actions(state, [])
    assert actions == batch_table_semantics.CONSUMER_ACTIONS


def test_repeated_read_block_is_classified_for_consumer_recovery() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_read(
        state,
        error={
            "type": "RepeatedActionBlocked",
            "blocked_action": "spreadsheet.read_file",
            "argument_signature": "synthetic",
            "error_signature": "PATH_NOT_FOUND",
            "block_scope": "episode",
        },
    )

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_consecutive_failed_reads_keep_consumer_recovery_classification() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_read(
        state,
        error={"type": "ValueError", "detail": "synthetic schema failure"},
    )
    _append_failed_read(
        state,
        step=4,
        error={
            "type": "RepeatedActionBlocked",
            "blocked_action": "spreadsheet.read_file",
            "argument_signature": "synthetic",
            "error_signature": "SCHEMA_ERROR",
            "block_scope": "episode",
        },
    )

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_successful_changed_read_keeps_lease_despite_old_read_block() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_read(
        state,
        error={"type": "ValueError", "detail": "synthetic schema failure"},
    )
    _append_failed_read(
        state,
        step=4,
        error={
            "type": "RepeatedActionBlocked",
            "blocked_action": "spreadsheet.read_file",
            "argument_signature": "synthetic",
            "error_signature": "SCHEMA_ERROR",
            "block_scope": "episode",
        },
    )
    _append_successful_read(state, step=5, target_range="A2:I10")

    assert state.active_request_blocks()
    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_successful_read_does_not_override_unrelated_active_block() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    state.events.append(
        ExecutionEvent(
            step=3,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "gui",
                "tool": "gui_action",
                "action": "click",
                "arguments": {"x": 5, "y": 5},
            },
            executed=False,
            error={
                "type": "RepeatedActionBlocked",
                "blocked_action": "gui_action",
                "argument_signature": "synthetic",
                "error_signature": "GUI_ERROR",
                "block_scope": "episode",
            },
        )
    )
    _append_successful_read(state, step=4, target_range="A2:I10")

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == ()


def test_structured_read_failure_uses_consumer_recovery() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_read(
        state,
        error={
            "status": "error",
            "error_code": "SPREADSHEET_PATH_NOT_FOUND",
            "error": "the requested spreadsheet path does not exist",
        },
    )

    assert batch_table_semantics.pending_consumer_recovery_actions(state, [])


def test_schema_read_failure_uses_consumer_recovery() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_read(
        state,
        error={
            "type": "ValueError",
            "detail": (
                "arguments violate the current model-visible schema for "
                "adapter__spreadsheet_read_file"
            ),
        },
    )

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_non_adapter_read_failure_does_not_claim_consumer_recovery() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_read(
        state,
        error={"type": "ValueError", "detail": "synthetic GUI boundary failure"},
    )
    state.events[-1].proposed["kind"] = "gui"

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == ()


def test_read_failure_after_successful_write_does_not_retain_consumer_lease() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_write(state)
    state.events[-1].executed = True
    state.events[-1].error = None
    state.events[-1].result = {"adapter_response": {"status": "ok"}}
    _append_failed_read(
        state,
        step=4,
        error={"type": "ValueError", "detail": "synthetic schema failure"},
    )

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == ()


def test_read_failure_after_recoverable_write_keeps_consumer_lease() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_write(state)
    _append_failed_read(
        state,
        step=4,
        error={"type": "ValueError", "detail": "synthetic schema failure"},
    )

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == (
        batch_table_semantics.CONSUMER_ACTIONS
    )


def test_unrecoverable_failed_write_releases_consumer_recovery_surface() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    _append_failed_write(state)
    state.events[-1].error = {
        "status": "error",
        "error": {"code": "PATH_NOT_FOUND"},
    }

    assert batch_table_semantics.pending_consumer_recovery_actions(state, []) == ()
    names = {tool["function"]["name"] for tool in _agent(include_gui=True).tools(state)}
    assert "tools_search" in names
    assert "gui_action" not in names


def test_successful_consumer_keeps_readback_actions_pending() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    state.events.append(
        ExecutionEvent(
            step=3,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__spreadsheet_write_range",
                "action": "spreadsheet.write_range",
                "arguments": {
                    "sheet": "Sheet1",
                    "range": "A2:B4",
                    "values": [["a", 1], ["b", 2], ["c", 3]],
                },
            },
            executed=True,
            result={"adapter_response": {"status": "ok", "result": {}}},
        )
    )

    actions = batch_table_semantics.pending_post_mutation_actions(state, [])
    assert actions == (
        batch_table_semantics.READ_ACTION,
        batch_table_semantics.WRITE_ACTION,
        batch_table_semantics.SAVE_ACTION,
    )


def test_post_mutation_surface_ends_after_readback_and_save() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)
    for step, action, tool in (
        (3, batch_table_semantics.WRITE_ACTION, "adapter__spreadsheet_write_range"),
        (4, batch_table_semantics.READ_ACTION, "adapter__spreadsheet_read_file"),
        (5, batch_table_semantics.SAVE_ACTION, "adapter__spreadsheet_save"),
    ):
        state.events.append(
            ExecutionEvent(
                step=step,
                timestamp_utc="2026-08-29T00:00:00Z",
                proposed={
                    "kind": "adapter",
                    "tool": tool,
                    "action": action,
                    "arguments": {},
                },
                executed=True,
                result={"adapter_response": {"status": "ok", "result": {}}},
            )
        )

    assert batch_table_semantics.pending_post_mutation_actions(state, []) == ()


def test_multi_app_write_exposes_read_then_native_save_route() -> None:
    state = _state()
    _append_batch_result(state)
    _append_inspect_result(state)

    def add(step: int, action: str) -> None:
        state.events.append(
            ExecutionEvent(
                step=step,
                timestamp_utc="2026-08-29T00:00:00Z",
                proposed={
                    "kind": "adapter",
                    "tool": "adapter__adapter_call",
                    "action": "adapter.call",
                    "arguments": {
                        "adapter": "libreoffice_calc",
                        "action": action,
                        "payload": {"params": {}},
                    },
                },
                executed=True,
                result={"adapter_response": {"status": "ok", "result": {}}},
            )
        )

    add(3, "range.write")
    assert batch_table_semantics.next_post_mutation_route(state) == (
        "libreoffice_calc",
        "range.read",
    )
    add(4, "range.read")
    assert batch_table_semantics.next_post_mutation_route(state) == (
        "libreoffice_calc",
        "workbook.save",
    )
    add(5, "workbook.save")
    assert batch_table_semantics.next_post_mutation_route(state) is None


def test_decimal_rate_source_lease_stays_open_until_all_nine_ecs_years() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate from ECS PDF files for years 2015-2023 and "
            "fill the spreadsheet table for each university as decimal values; "
            "use supported proposals divided by total applications."
        )
    )
    _append_batch_result(state, count=1, input_pattern="ecs15.pdf")
    assert not batch_table_semantics.requested_fields_complete(state)

    state.events.clear()
    _append_batch_result(state, count=9, input_pattern="ecs*.pdf")
    state.events[-1].result["adapter_response"]["result"]["files"] = [
        {"path": f"/tmp/ecs{year}.pdf", "text": "year data"}
        for year in range(15, 24)
    ]
    assert batch_table_semantics.requested_fields_complete(state)


def test_native_ecs_completion_keeps_workbook_inspect_route_without_legacy_batch() -> None:
    """Native per-PDF observations must advance to Calc inspection directly."""
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the ECS PDF "
            "files, fill the spreadsheet, and enter the values as decimals."
        )
    )
    for index, year in enumerate(range(2015, 2024), start=1):
        _append_structured_rate_observation(state, year=year, step=index)

    assert batch_table_semantics.native_pdf_table_observation_complete(state)
    assert batch_table_semantics.batch_route_allowed_after_completion(
        state, "workbook.inspect"
    )
    assert not batch_table_semantics.batch_route_allowed_after_completion(
        state, "workbook.create_new"
    )


def test_native_ecs_completion_after_inspect_only_exposes_range_consumer_routes() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the ECS PDF "
            "files, fill the spreadsheet, and enter the values as decimals."
        )
    )
    for index, year in enumerate(range(2015, 2024), start=1):
        _append_structured_rate_observation(state, year=year, step=index)
    _append_inspect_result(state, step=10)

    # After the live workbook probe, the native PDF matrix is already the
    # source of truth; exposing another read only invites an unbounded retry.
    assert not batch_table_semantics.batch_route_allowed_after_completion(
        state, "range.read"
    )
    assert batch_table_semantics.batch_route_allowed_after_completion(
        state, "range.write"
    )
    for forbidden in (
        "workbook.inspect",
        "workbook.create_new",
        "pdf.tables.inspect",
        "pdf.extract_text_batch",
    ):
        assert not batch_table_semantics.batch_route_allowed_after_completion(
            state, forbidden
        )


def test_native_ecs_workflow_completion_requires_save_after_readback() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the ECS PDF "
            "files, fill the spreadsheet, and enter the values as decimals."
        )
    )
    for index, year in enumerate(range(2015, 2024), start=1):
        _append_structured_rate_observation(state, year=year, step=index)
    _append_inspect_result(state, step=10)

    def add(step: int, action: str) -> None:
        state.events.append(
            ExecutionEvent(
                step=step,
                timestamp_utc="2026-08-29T00:00:00Z",
                proposed={
                    "kind": "adapter",
                    "tool": "adapter__adapter_call",
                    "action": "adapter.call",
                    "arguments": {
                        "adapter": "libreoffice_calc",
                        "action": action,
                        "payload": {"params": {}},
                    },
                },
                executed=True,
                result={"adapter_response": {"status": "ok", "result": {}}},
            )
        )

    add(11, "range.write")
    add(12, "range.read")
    assert not batch_table_semantics.native_pdf_table_workflow_complete(state)
    add(13, "workbook.save")
    assert batch_table_semantics.native_pdf_table_workflow_complete(state)


def test_create_after_failed_probe_enters_creation_lifecycle() -> None:
    state = _state(instruction="For each source PDF, create a new spreadsheet.")
    _append_batch_result(state)
    _append_failed_inspect(state)
    _append_header_only_create(state)

    assert batch_table_semantics.stage_actions(
        state, [batch_table_semantics.CREATE_ACTION]
    ) == [batch_table_semantics.WRITE_ACTION]
    assert batch_table_semantics.completion_errors(state)


def test_creation_constraints_begin_only_after_successful_model_create() -> None:
    state = _state(instruction="For each source PDF, create a new spreadsheet.")
    _append_batch_result(state)

    assert batch_table_semantics.completion_errors(state) == []
    _append_inspect_result(state)
    assert batch_table_semantics.completion_errors(state) == []

    _append_header_only_create(state)
    errors = batch_table_semantics.completion_errors(state)
    assert errors
    assert "exactly 3" in errors[0]

    argument_errors = batch_table_semantics.argument_contract_errors(
        state,
        batch_table_semantics.CREATE_ACTION,
        {
            "output_path": "/tmp/other.ods",
            "headers": ["University"],
            "rows": [["one"], ["two"]],
        },
    )
    assert argument_errors
    assert "exactly 3" in argument_errors[0]

    wrapped_errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "workbook.create_new",
            "payload": {
                "params": {
                    "output_path": "/tmp/other.ods",
                    "headers": ["Name"],
                    "rows": [["two"], ["null"], ["three"]],
                }
            },
        },
    )
    assert wrapped_errors
    assert "placeholder" in wrapped_errors[0]
    assert "retry workbook.create_new" in wrapped_errors[0]
    assert "without rereading" in wrapped_errors[0]


def test_create_new_rejects_nested_headers_before_adapter_execution() -> None:
    state = _state(instruction="For each source PDF, create a new spreadsheet.")
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "workbook.create_new",
            "payload": {
                "params": {
                    "output_path": "/tmp/other.ods",
                    "headers": [["Year", "#Applied"]],
                    "rows": [["2019", 1]],
                }
            },
        },
    )
    assert errors
    assert "flat" in errors[0]
    assert "[\"Year\", \"#Applied\"]" in errors[0]


def test_create_new_accepts_flat_string_headers_at_contract_boundary() -> None:
    state = _state(instruction="For each source PDF, create a new spreadsheet.")
    assert batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "workbook.create_new",
            "payload": {
                "params": {
                    "output_path": "/tmp/other.ods",
                    "headers": ["Year", "#Applied"],
                    "rows": [["2019", 1]],
                }
            },
        },
    ) == []


def test_create_new_reports_sort_repair_without_source_replay() -> None:
    state = _state(
        instruction=(
            "Extract the name, e-mail, and affiliation of the first author from "
            "each paper and organize them in an Excel table sorted by name."
        )
    )
    _append_batch_result(state, count=2, step=1, truncated=True)
    files = state.events[0].result["adapter_response"]["result"]["files"]
    files[0]["text"] = "Zed Author\nExample University\nzed@example.edu"
    files[1]["text"] = "Ada Author\nExample University\nada@example.edu"
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "workbook.create_new",
            "payload": {
                "params": {
                    "output_path": "/tmp/authors.xlsx",
                    "headers": ["Name", "Affiliation", "Email"],
                    "rows": [
                        ["Zed Author", "Example University", "zed@example.edu"],
                        ["Ada Author", "Example University", "ada@example.edu"],
                    ],
                }
            },
        },
    )
    assert errors
    assert "requested observed sort column" in errors[0]
    assert "without rereading the source" in errors[0]


def test_create_new_rejects_guessed_email_not_observed_in_pdf() -> None:
    state = _state(
        instruction=(
            "Extract the name, e-mail, and affiliation of the first author from "
            "each paper and organize them in an Excel table."
        )
    )
    _append_batch_result(state, count=1, step=1, truncated=True)
    state.events[0].result["adapter_response"]["result"]["files"][0]["text"] = (
        "Runliang Niu\nSchool of Artificial Intelligence\n"
        "{niurl19,jdLi21}@mails.jlu.edu.cn"
    )
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "workbook.create_new",
            "payload": {
                "params": {
                    "output_path": "/tmp/authors.xlsx",
                    "headers": ["Name", "Email", "Affiliation"],
                    "rows": [["Runliang Niu", "niu@jlu.edu.cn", "School of Artificial Intelligence"]],
                }
            },
        },
    )
    assert errors
    assert "exact complete address observed" in " ".join(errors)
    assert "do not derive" in " ".join(errors)
    assert "{niurl19,jdLi21}@mails.jlu.edu.cn" in " ".join(errors)


def test_create_new_rejects_cross_document_first_author_email_assembly() -> None:
    state = _state(
        instruction=(
            "Extract the name, e-mail, and affiliation of the first author from "
            "each paper and organize them in an Excel table."
        )
    )
    _append_batch_result(state, count=1, step=1, truncated=True)
    state.events[0].result["adapter_response"]["result"]["files"][0]["text"] = (
        "Example Paper\n"
        "Runliang Niu1, Jindong Li1, Shiqi Wang1\n"
        "School of Artificial Intelligence, Jilin University\n"
        "{niurl19,jdLi21}@mails.jlu.edu.cn"
    )
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "workbook.create_new",
            "payload": {
                "params": {
                    "output_path": "/tmp/authors.xlsx",
                    "headers": ["Name", "Email", "Affiliation"],
                    "rows": [[
                        "Runliang Niu",
                        "jdLi21@mails.jlu.edu.cn",
                        "School of Artificial Intelligence, Jilin University",
                    ]],
                }
            },
        },
    )
    assert errors
    assert "first-author/email assembly" in " ".join(errors)
    assert "niurl19@mails.jlu.edu.cn" in " ".join(errors)


def _append_observed_rate_table(state: RuntimeState, *, step: int = 2) -> None:
    source_files = state.events[0].result["adapter_response"]["result"]["files"]
    for index, item in enumerate(source_files):
        _append_pdf_table_result(
            state,
            input_path=item["path"],
            step=step + index,
        )
    headers = [
        "Year",
        "CityU",
        "HKBU",
        "LU",
        "CUHK",
        "HKIEd (EduHK)",
        "PolyU",
        "HKUST",
        "HKU",
    ]
    rows = [headers] + [[str(year), *([""] * 8)] for year in range(2015, 2024)]
    state.events.append(
        ExecutionEvent(
            step=step + len(source_files),
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__adapter_call",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "libreoffice_calc",
                    "action": "range.read",
                    "payload": {"params": {"sheet": "Sheet1", "range": "A1:I10"}},
                },
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "action": "adapter.call",
                    "result": {
                        "action": "range.read",
                        "adapter": "libreoffice_calc",
                        "response": {
                            "status": "ok",
                            "result": {
                                "sheet": "Sheet1",
                                "range": "A1:I10",
                                "display_text": rows,
                            },
                        },
                    },
                }
            },
        )
    )


def _append_structured_rate_observation(
    state: RuntimeState, *, year: int, step: int
) -> None:
    rows = [
        ["Panel / Subject Discipline", *([None] * 36)],
        [None, *(["Application", None, "Supported", None] * 9)],
        [None, *(["No", "Amt", "No", "Amt"] * 9)],
        ["Total"],
    ]
    total = rows[-1]
    for university_index in range(8):
        application = 10 + year - 2015 + university_index
        supported = 2 + university_index
        total.extend([str(application), "0", str(supported), "0"])
    total.extend(["0", "0", "0", "0"])
    state.events.append(
        ExecutionEvent(
            step=step,
            timestamp_utc="2026-08-29T00:00:00Z",
            proposed={
                "kind": "adapter",
                "tool": "adapter__adapter_call",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "pdf.tables.inspect",
                    "payload": {
                        "params": {
                            "input_path": f"/tmp/ecs{year - 2000}.pdf",
                            "page": 1,
                            "table_index": 0,
                        }
                    },
                },
            },
            executed=True,
            result={
                "adapter_response": {
                    "status": "ok",
                    "result": {
                        "adapter": "os",
                        "action": "pdf.tables.inspect",
                        "response": {
                            "status": "ok",
                            "result": {
                                "input_path": f"/tmp/ecs{year - 2000}.pdf",
                                "table_count": 1,
                                "row_count": len(rows),
                                "column_count": 37,
                                "rows": rows,
                            },
                        },
                    },
                }
            },
        )
    )


def test_rate_matrix_write_rejects_fraction_content_and_wrong_shape() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the PDF files, "
            "fill the spreadsheet, and enter the values as decimals."
        )
    )
    _append_batch_result(state, count=9)
    _append_observed_rate_table(state)
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "range.write",
            "payload": {
                "params": {
                    "sheet": "Sheet1",
                    "range": "B2:I10",
                    "values": [["56/77"] * 9 for _ in range(6)],
                }
            },
        },
    )
    joined = " ".join(errors)
    assert "9 rows x 8 university columns" in joined
    assert "B2:I10" in joined
    assert "quoted fractions" in joined


def test_rate_matrix_write_rejects_numeric_shape_without_observation_derived_values() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the PDF files, "
            "fill the spreadsheet, and enter the values as decimals."
        )
    )
    _append_batch_result(state, count=9)
    _append_observed_rate_table(state)
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "range.write",
            "payload": {
                "params": {
                    "sheet": "Sheet1",
                    "range": "B2:I10",
                    "values": [[0.5] * 8 for _ in range(9)],
                }
            },
        },
    )
    assert errors
    assert "parsed in order" in " ".join(errors)
    assert "do not submit a guessed or uniform matrix" in " ".join(errors)


def test_rate_matrix_contract_uses_workbook_read_file_geometry() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the PDF files, "
            "fill the spreadsheet, and enter the values as decimals."
        )
    )
    _append_batch_result(state, count=9)
    _append_observed_rate_table(state)
    read_event = state.events[-1]
    read_event.proposed["arguments"]["action"] = "workbook.read_file"
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "range.write",
            "payload": {
                "params": {
                    "sheet": "Sheet1",
                    "range": "A1:I10",
                    "values": [[0.5] * 9 for _ in range(9)],
                }
            },
        },
    )
    assert errors
    assert "9 rows x 8 university columns" in " ".join(errors)
    assert "B2:I10" in " ".join(errors)


def test_rate_matrix_contract_derives_values_from_structured_pdf_tables() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the PDF files, "
            "fill the spreadsheet, and enter the values as decimals."
        )
    )
    _append_batch_result(state, count=9)
    for index, item in enumerate(
        state.events[0].result["adapter_response"]["result"]["files"]
    ):
        year = 2015 + index
        item["path"] = f"/tmp/ecs{year - 2000}.pdf"
        _append_structured_rate_observation(state, year=year, step=index + 2)
    _append_observed_rate_table(state, step=20)

    expected = batch_table_semantics._observed_decimal_rate_matrix(state)
    assert expected is not None
    assert len(expected) == 9
    assert all(len(row) == 8 for row in expected)

    wrong_errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "range.write",
            "payload": {
                "params": {
                    "sheet": "Sheet1",
                    "range": "B2:I10",
                    "values": [[0.5] * 8 for _ in range(9)],
                }
            },
        },
    )
    assert any("Application/Supported pair" in error for error in wrong_errors)

    correct_errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "range.write",
            "payload": {
                "params": {
                    "sheet": "Sheet1",
                    "range": "B2:I10",
                    "values": expected,
                }
            },
        },
    )
    assert correct_errors == []


def test_rate_matrix_schema_binds_values_to_observation_derived_const() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the ECS PDF "
            "files, fill the spreadsheet, and enter the values as decimals."
        )
    )
    _append_batch_result(state, count=9)
    for index, year in enumerate(range(2015, 2024), start=1):
        _append_structured_rate_observation(state, year=year, step=index)
    _append_observed_rate_table(state, step=20)
    expected = batch_table_semantics._observed_decimal_rate_matrix(state)
    assert expected is not None
    function = {
        "name": "adapter__adapter_call",
        "parameters": {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "properties": {
                        "params": {
                            "type": "object",
                            "properties": {
                                "sheet": {"type": "string"},
                                "range": {"type": "string"},
                                "values": {"type": "array"},
                            },
                        }
                    },
                }
            },
        },
    }

    batch_table_semantics.constrain_tool_schema(function, state)

    values = function["parameters"]["properties"]["payload"]["properties"]["params"][
        "properties"
    ]["values"]
    assert values["const"] == [
        [round(float(value), 6) for value in row] for row in expected
    ]


def test_rate_matrix_target_and_schema_bind_after_workbook_inspect_only() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the ECS PDF "
            "files, fill the spreadsheet, and enter the values as decimals."
        )
    )
    _append_batch_result(state, count=9)
    for index, year in enumerate(range(2015, 2024), start=1):
        _append_structured_rate_observation(state, year=year, step=index)
    _append_inspect_result(state, step=20)
    inspect_result = state.events[-1].result["adapter_response"]["result"]["response"]["result"]
    inspect_result["sheets"] = [
        {
            "name": "Sheet1",
            "used_range": {
                "start_row": 0,
                "start_column": 0,
                "end_row": 9,
                "end_column": 8,
            },
        }
    ]

    expected = batch_table_semantics._observed_decimal_rate_matrix(state)
    target = batch_table_semantics._observed_decimal_rate_target(state)
    assert expected is not None
    assert target == {
        "sheet": "Sheet1",
        "range": "B2:I10",
        "record_count": 9,
        "column_count": 8,
        "headers": [],
    }
    function = {
        "name": "adapter__adapter_call",
        "parameters": {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "properties": {
                        "params": {
                            "type": "object",
                            "properties": {
                                "sheet": {"type": "string"},
                                "range": {"type": "string"},
                                "values": {"type": "array"},
                            },
                        }
                    },
                }
            },
        },
    }
    batch_table_semantics.constrain_tool_schema(function, state)
    values = function["parameters"]["properties"]["payload"]["properties"]["params"][
        "properties"
    ]["values"]
    assert values["const"] == [
        [round(float(value), 6) for value in row] for row in expected
    ]


def test_completed_ecs_projection_carries_all_years_in_compact_handoff() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the ECS PDF "
            "files, fill the spreadsheet, and enter the values as decimals."
        )
    )
    events = []
    for index, year in enumerate(range(2015, 2024), start=1):
        _append_structured_rate_observation(state, year=year, step=index)
        event = state.events[-1]
        rows = event.result["adapter_response"]["result"]["response"]["result"]["rows"]
        event.result = {
            "context_hint": {
                "downstream_context": {
                    "observation_type": "pdf_table",
                    "input_path": f"/tmp/ecs{year - 2000}.pdf",
                    "row_count": len(rows),
                    "column_count": 37,
                    "rows": rows,
                }
            }
        }
        events.append((event, f"/tmp/ecs{year - 2000}.pdf"))

    projected = adapter_results._compact_completed_ecs_table_events(
        state.events, "multi_apps"
    )
    latest = next(event for event in projected if event.step == 9)
    aggregate = latest.result["context_hint"]["downstream_context"][
        "ecs_structured_observations"
    ]
    assert len(aggregate) == 9
    assert [item["input_path"] for item in aggregate] == [
        f"/tmp/ecs{year - 2000}.pdf" for year in range(2015, 2024)
    ]
    assert all(
        len(item["application_no"]) == 8
        and len(item["supported_no"]) == 8
        and item["calculation"] == "supported_no / application_no"
        for item in aggregate
    )


def test_rate_matrix_rejects_nonadjacent_application_supported_header() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the ECS PDF "
            "files, fill the spreadsheet, and enter the values as decimals."
        )
    )
    _append_batch_result(state, count=9)
    for index, year in enumerate(range(2015, 2024), start=1):
        _append_structured_rate_observation(state, year=year, step=index)
    # In the second university block, swap the two semantic headers.  Fixed
    # offsets must not turn that malformed observation into a plausible ratio.
    table_event = state.events[2]
    rows = table_event.result["adapter_response"]["result"]["response"]["result"]["rows"]
    rows[1][5], rows[1][7] = rows[1][7], rows[1][5]

    assert batch_table_semantics._observed_decimal_rate_matrix(state) is None


def test_rate_matrix_does_not_fall_back_to_flattened_text() -> None:
    state = _state(
        instruction=(
            "Extract the pass rate for each university and each year from the ECS PDF "
            "files, fill the spreadsheet, and enter the values as decimals."
        )
    )
    _append_batch_result(state, count=9)
    for item in state.events[0].result["adapter_response"]["result"]["files"]:
        item["text"] = "Total 10 0 2 0 10 0 2 0 10 0 2 0"
    assert batch_table_semantics._observed_decimal_rate_matrix(state) is None


def _append_grf_table_observation(
    state: RuntimeState, *, year: int, applied: int, supported: int, step: int
) -> None:
    rows = [
        ["Panel / Subject Discipline", *([None] * 36)],
        [None] * 37,
        [None] * 37,
        [None] * 37,
    ]
    rows[0][29] = "HKU"
    rows[1][29] = "Application"
    rows[1][31] = "Supported"
    rows[2][29] = "No"
    rows[2][31] = "No"
    rows[3][0] = (
        "Engineering\nCivil Engineering,\nSurveying, Building &\nConstruction\n"
        "Computing Science &\nInformation Technology\nElectrical & Electronic\n"
        "Engineering\nMechanical, Production &\nIndustrial Engineering"
    )
    rows[3][29] = f"34\n{applied}\n20\n22"
    rows[3][31] = f"11\n{supported}\n8\n10"
    _append_pdf_table_result(state, input_path=f"/tmp/grf{year - 2000}.pdf", step=step)
    result = state.events[-1].result["adapter_response"]["result"]["response"]["result"]
    result["row_count"] = len(rows)
    result["column_count"] = 37
    result["rows"] = rows


def test_grf_target_resolver_binds_wrapped_subject_and_hku_columns() -> None:
    state = _state(
        instruction=(
            'Extract HKU\'s GRF application results for the "Computing Science & '
            'Information Technology" discipline from 2019 to 2023. For each year, '
            'extract the number of applications and number supported.'
        )
    )
    expected = [(2019, 25, 7), (2020, 17, 7), (2021, 23, 7), (2022, 23, 9), (2023, 20, 5)]
    for step, (year, applied, supported) in enumerate(expected, start=1):
        _append_grf_table_observation(
            state, year=year, applied=applied, supported=supported, step=step
        )

    records, errors = batch_table_semantics._observed_grf_records(state)
    assert errors == []
    assert [records[year]["applied"] for year, _, _ in expected] == [25, 17, 23, 23, 20]
    assert [records[year]["supported"] for year, _, _ in expected] == [7, 7, 7, 9, 5]
    assert [records[year]["subject_index"] for year, _, _ in expected] == [1] * 5
    assert records[2019]["application_column"] == 29
    assert records[2019]["supported_column"] == 31


def test_grf_create_rejects_misaligned_values_before_adapter_execution() -> None:
    state = _state(
        instruction=(
            'Extract HKU\'s GRF application results for the "Computing Science & '
            'Information Technology" discipline from 2019 to 2023. Extract the '
            'number of applications and number supported and save them in a table.'
        )
    )
    expected = [(2019, 25, 7), (2020, 17, 7), (2021, 23, 7), (2022, 23, 9), (2023, 20, 5)]
    for step, (year, applied, supported) in enumerate(expected, start=1):
        _append_grf_table_observation(
            state, year=year, applied=applied, supported=supported, step=step
        )
    wrong_rows = [
        ["2019", 67, 14, 20.9],
        ["2020", 81, 17, 20.99],
        ["2021", 79, 16, 20.25],
        ["2022", 88, 19, 21.59],
        ["2023", 81, 17, 20.99],
    ]
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "workbook.create_new",
            "payload": {
                "params": {
                    "output_path": "/tmp/GRF-p5y.xlsx",
                    "headers": ["Year", "#Applied", "#Supported", "Success Rate"],
                    "rows": wrong_rows,
                }
            },
        },
    )
    joined = " ".join(errors)
    assert "does not match the observed HKU target cell" in joined
    assert "expected 25" in joined
    assert "expected 28.0" in joined


def test_grf_create_accepts_only_filename_ordered_observed_values() -> None:
    state = _state(
        instruction=(
            'Extract HKU\'s GRF application results for the "Computing Science & '
            'Information Technology" discipline from 2019 to 2023. Extract the '
            'number of applications and number supported and save them in a table.'
        )
    )
    expected = [(2019, 25, 7), (2020, 17, 7), (2021, 23, 7), (2022, 23, 9), (2023, 20, 5)]
    for step, (year, applied, supported) in enumerate(expected, start=1):
        _append_grf_table_observation(
            state, year=year, applied=applied, supported=supported, step=step
        )
    rows = [
        [str(year), applied, supported, round(supported / applied * 100, 2)]
        for year, applied, supported in expected
    ]
    assert batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "workbook.create_new",
            "payload": {
                "params": {
                    "output_path": "/tmp/GRF-p5y.xlsx",
                    "headers": ["Year", "#Applied", "#Supported", "Success Rate"],
                    "rows": rows,
                }
            },
        },
    ) == []


def test_create_new_rejects_shortened_observed_affiliation_and_email_header() -> None:
    state = _state(
        instruction=(
            "Extract the name, e-mail, and affiliation of the first author from "
            "each paper and organize them in an Excel table."
        )
    )
    _append_batch_result(state, count=1, step=1, truncated=True)
    state.events[0].result["adapter_response"]["result"]["files"][0]["text"] = (
        "ScreenAgent\n"
        "Runliang Niu1 , Jindong Li1\n"
        "School of Artificial Intelligence, Jilin University\n"
        "{niurl19,jdLi21}@mails.jlu.edu.cn"
    )
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "libreoffice_calc",
            "action": "workbook.create_new",
            "payload": {
                "params": {
                    "output_path": "/tmp/authors.xlsx",
                    "headers": ["Name", "Email", "Affiliation"],
                    "rows": [[
                        "Runliang Niu",
                        "niurl19@mails.jlu.edu.cn",
                        "Jilin University",
                    ]],
                }
            },
        },
    )
    joined = " ".join(errors)
    assert "complete affiliation line" in joined
    assert "School of Artificial Intelligence, Jilin University" in joined
    assert "header" in joined and "Mail" in joined


def test_requested_fields_complete_stops_pdf_continuation_before_eof() -> None:
    state = _state(
        instruction=(
            "Extract the name, e-mail, and affiliation of the first author from "
            "each paper and organize them in an Excel table."
        )
    )
    _append_batch_result(state, count=4, step=1, truncated=True)
    texts = [
        "Xiang Deng\nThe Ohio State University\ndeng.595@osu.edu\nremaining body",
        "Jing Yu Koh\nCarnegie Mellon University\njingyuk@cs.cmu.edu\nremaining body",
        "Runliang Niu\nSchool of Artificial Intelligence, Jilin University\n"
        "{niurl19,jdLi21}@mails.jlu.edu.cn\nremaining body",
        "Chi Zhang\nTencent\n{johnczhang,jayzyang}@tencent.com\nremaining body",
    ]
    files = state.events[0].result["adapter_response"]["result"]["files"]
    for file, text in zip(files, texts):
        file["text"] = text
    _append_inspect_result(state, step=2)

    assert batch_table_semantics.requested_fields_complete(state)
    assert batch_table_semantics.batch_continuation_action(state) is None
    assert batch_table_semantics.stage_actions(state, []) == [
        batch_table_semantics.WRITE_ACTION,
        batch_table_semantics.READ_ACTION,
        batch_table_semantics.SAVE_ACTION,
        batch_table_semantics.CREATE_ACTION,
    ]


def test_requested_fields_complete_reads_model_visible_text_chunks() -> None:
    state = _state(
        instruction=(
            "Extract the name, e-mail, and affiliation of the first author from "
            "each paper and organize them in an Excel table."
        )
    )
    _append_batch_result(state, count=4, step=1, truncated=True)
    texts = [
        ("Xiang Deng", "The Ohio State University", "deng.595@osu.edu"),
        ("Jing Yu Koh", "Carnegie Mellon University", "jingyuk@cs.cmu.edu"),
        ("Runliang Niu", "School of Artificial Intelligence", "niurl19@mails.jlu.edu.cn"),
        ("Chi Zhang", "Tencent", "johnczhang@tencent.com"),
    ]
    files = state.events[0].result["adapter_response"]["result"]["files"]
    for file, (name, affiliation, email) in zip(files, texts):
        file.pop("text", None)
        file["chunks"] = [{"type": "text", "text": f"{name}\n{affiliation}\n{email}"}]
    _append_inspect_result(state, step=2)

    assert batch_table_semantics.requested_fields_complete(state)
    assert batch_table_semantics.batch_continuation_action(state) is None


def test_complete_fields_expose_create_before_target_probe() -> None:
    state = _state(
        instruction=(
            "Extract the name, e-mail, and affiliation of the first author from "
            "each paper and organize them in an Excel table."
        )
    )
    _append_batch_result(state, count=1, step=1, truncated=True)
    state.events[0].result["adapter_response"]["result"]["files"][0]["text"] = (
        "First Author\nExample University\nfirst@example.edu"
    )
    assert batch_table_semantics.stage_actions(
        state, [batch_table_semantics.INSPECT_ACTION]
    ) == [batch_table_semantics.INSPECT_ACTION, batch_table_semantics.CREATE_ACTION]


def test_completed_fields_reject_continuation_at_contract_boundary() -> None:
    state = _state(
        instruction=(
            "Extract the name, e-mail, and affiliation of the first author from "
            "each paper and organize them in an Excel table."
        )
    )
    _append_batch_result(state, count=1, step=1, truncated=True)
    state.events[0].result["adapter_response"]["result"]["files"][0]["text"] = (
        "First Author\nExample University\nfirst@example.edu"
    )
    errors = batch_table_semantics.argument_contract_errors(
        state,
        "adapter.call",
        {
            "adapter": "os",
            "action": "pdf.extract_text_batch",
            "payload": {"params": {"input_pattern": "source.pdf"}},
        },
    )
    assert errors
    assert "already observed" in errors[0]


def test_create_before_latest_batch_does_not_satisfy_current_creation_lifecycle() -> (
    None
):
    state = _state(instruction="For each source PDF, create a new spreadsheet.")
    _append_header_only_create(state)
    # The create above predates the producer that starts this workflow and
    # must not activate the current creation lifecycle's completion checks.
    _append_batch_result(state, step=4)

    assert batch_table_semantics.completion_errors(state) == []


def test_batch_stage_is_task_id_invariant_and_does_not_echo_sensitive_metadata() -> (
    None
):
    first = _state(task_id="123e4567-e89b-72d3-a456-426614174000")
    second = _state(task_id="different-task")
    _append_batch_result(first)
    _append_batch_result(second)
    first.events[0].result["task_id"] = "evaluator-secret-42"

    first_surface = _agent().tools(first)
    second_surface = _agent().tools(second)
    assert [tool["function"]["name"] for tool in first_surface] == [
        tool["function"]["name"] for tool in second_surface
    ]
    serialized = json.dumps(first_surface, ensure_ascii=False)
    assert "123e4567" not in serialized
    assert "evaluator-secret-42" not in serialized
    assert "golden" not in serialized.casefold()
