from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from calc_adapter import uno_worker
from calc_adapter.errors import AdapterError
from calc_adapter.service import create_app
from integrations.lite_agent.adapter_executor import AdapterExecutor
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools, search_actions


def routes(query):
    return [
        (item["adapter"], item["downstream_action"])
        for item in search_actions("multi_apps", query, limit=6, strict_generic=True)
    ]


@pytest.mark.parametrize("query", [
    "get current workbook path",
    "read the spreadsheet already open in Calc",
    "find active spreadsheet identity and worksheet ranges",
])
def test_active_workbook_inspection_is_retrievable_without_knowing_its_route(query):
    assert ("libreoffice_calc", "workbook.inspect") in routes(query)[:3]


@pytest.mark.parametrize("query, expected", [
    ("read local CSV file", ("libreoffice_calc", "workbook.read_file")),
    ("find invoice.xlsx file path", ("os", "filesystem.find")),
    ("find files in current vscode workspace", ("vs_code", "workspace.find_files")),
])
def test_active_workbook_keywords_preserve_explicit_file_and_editor_discovery(query, expected):
    assert expected in routes(query)[:3]


def test_discovered_active_workbook_contract_needs_no_guessed_path():
    tools = constrain_adapter_call_routes(
        build_tools(
            "multi_apps", ["adapter.call"], include_gui=False,
            include_control_tools=False, strict_generic=True,
        ),
        routes("get current workbook path"),
    )
    parameters = tools[0]["function"]["parameters"]
    assert "libreoffice_calc" in parameters["properties"]["adapter"]["enum"]
    assert "workbook.inspect" in parameters["properties"]["action"]["enum"]
    schema = parameters["properties"]["payload"]["properties"]["params"]
    assert "libreoffice_calc.workbook.inspect" in schema["description"]
    assert "No file path" in schema["description"]


def test_explicit_range_read_search_ignores_incidental_path() -> None:
    matches = search_actions(
        "multi_apps",
        'range.read path="file:///home/user/Documents/Fundings/supported_rate.xlsx" '
        'sheet="Sheet1" range="A1:I10"',
        limit=6,
        strict_generic=True,
    )

    assert [
        (item["adapter"], item["downstream_action"])
        for item in matches
    ] == [("libreoffice_calc", "range.read")]


def test_explicit_range_read_wins_over_pdf_rate_table_context() -> None:
    matches = search_actions(
        "multi_apps",
        "libreoffice_calc range.read",
        instruction="Read the PDF reports and calculate rates in the spreadsheet.",
        limit=6,
        strict_generic=True,
    )

    assert [
        (item["adapter"], item["downstream_action"])
        for item in matches
    ] == [("libreoffice_calc", "range.read")]


def test_active_workbook_read_alias_is_read_only() -> None:
    matches = search_actions(
        "multi_apps",
        'workbook.read sheet="Sheet1" range="A1:I10"',
        limit=6,
        strict_generic=True,
    )

    assert [
        (item["adapter"], item["downstream_action"])
        for item in matches
    ] == [("libreoffice_calc", "range.read")]


def test_explicit_workbook_create_route_is_retrievable() -> None:
    matches = search_actions(
        "multi_apps",
        "workbook.create_new",
        limit=6,
        strict_generic=True,
    )

    assert [
        (item["adapter"], item["downstream_action"])
        for item in matches
    ] == [("libreoffice_calc", "workbook.create_new")]


def test_provenance_failure_does_not_hide_pathless_workbook_inspect_route() -> None:
    route = ("libreoffice_calc", "workbook.inspect")
    state = RuntimeState(
        task_id="synthetic-provenance-recovery",
        domain="multi_apps",
        instruction="Inspect the open workbook.",
        events=[
            ExecutionEvent(
                step=1,
                timestamp_utc="2026-09-26T00:00:00Z",
                proposed={
                    "kind": "adapter",
                    "action": "adapter.call",
                    "arguments": {
                        "adapter": route[0],
                        "action": route[1],
                        "payload": {"params": {}},
                    },
                },
                executed=False,
                error={
                    "type": "ValueError",
                    "detail": (
                        "multi_apps.adapter.call requires a matching public "
                        "tools_search result before execution"
                    ),
                },
            ),
            ExecutionEvent(
                step=2,
                timestamp_utc="2026-09-26T00:00:01Z",
                proposed={
                    "kind": "adapter",
                    "action": "adapter.call",
                    "arguments": {
                        "adapter": route[0],
                        "action": route[1],
                        "payload": {"params": {}},
                    },
                },
                executed=False,
                error={
                    "type": "RepeatedActionBlocked",
                    "blocked_action": "adapter.call",
                    "argument_signature": "synthetic",
                    "error_signature": ["ValueError", "provenance", []],
                    "block_scope": "episode",
                    "previous_error": {
                        "type": "ValueError",
                        "detail": (
                            "multi_apps.adapter.call requires a matching public "
                            "tools_search result before execution"
                        ),
                    },
                },
            ),
        ],
    )

    assert state.blocked_routes() == set()
    matches = search_actions(
        "multi_apps",
        "libreoffice_calc workbook inspect",
        limit=6,
        strict_generic=True,
        excluded_routes=state.blocked_routes(),
    )
    assert (route[0], route[1]) in [
        (item["adapter"], item["downstream_action"]) for item in matches
    ]

    state.events.append(
        ExecutionEvent(
            step=3,
            timestamp_utc="2026-09-26T00:00:02Z",
            proposed={
                "kind": "catalog",
                "tool": "tools_search",
                "arguments": {"query": "libreoffice_calc workbook inspect"},
            },
            executed=True,
            result={
                "matches": [
                    {
                        "action": "adapter.call",
                        "adapter": route[0],
                        "downstream_action": route[1],
                    }
                ]
            },
        )
    )
    assert state.active_request_blocks() == {}


@pytest.fixture
def native_path_urls(monkeypatch):
    monkeypatch.setattr(uno_worker, "_file_url", lambda value: Path(value).as_uri())


def test_missing_file_reports_live_open_workbooks_without_selecting_or_reading_one(tmp_path, native_path_urls):
    documents = [
        SimpleNamespace(URL=(tmp_path / "native report.xlsx").as_uri(), Title="Native report"),
        SimpleNamespace(URL="", Title="Untitled 2"),
    ]
    session = SimpleNamespace(
        _documents=lambda: documents,
        _identity=lambda doc: {"url": doc.URL, "title": doc.Title},
    )
    params = {"path": str(tmp_path / "missing.xlsx")}
    original = deepcopy(params)

    with pytest.raises(AdapterError) as failure:
        uno_worker._read_file(session, params)

    assert failure.value.code == "FILE_NOT_FOUND"
    assert failure.value.details["path"] == original["path"]
    assert failure.value.details["open_documents"] == [
        {"url": documents[0].URL, "title": "Native report"},
        {"url": "", "title": "Untitled 2"},
    ]
    assert "not confirmed substitutes" in failure.value.message
    assert params == original


def test_missing_file_keeps_original_error_when_native_document_listing_fails(tmp_path, native_path_urls):
    def unavailable():
        raise RuntimeError("native document enumeration unavailable")

    session = SimpleNamespace(_documents=unavailable)
    with pytest.raises(AdapterError) as failure:
        uno_worker._read_file(session, {"path": str(tmp_path / "absent.ods")})

    assert failure.value.code == "FILE_NOT_FOUND"
    assert "open_documents" not in failure.value.details
    assert "enumeration unavailable" in failure.value.details["open_documents_error"]


def test_live_open_workbook_identity_survives_http_and_model_error_projection(
    tmp_path, native_path_urls, monkeypatch
):
    observed = {"url": (tmp_path / "observed.xlsx").as_uri(), "title": "Observed workbook"}
    session = SimpleNamespace(_documents=lambda: [object()], _identity=lambda _doc: observed)
    client = create_app(
        lifecycle=SimpleNamespace(listener_ready=lambda: True),
        runner=SimpleNamespace(run=lambda request: uno_worker._read_file(session, request.params)),
    ).test_client()

    def post(_url, *, json, timeout):
        response = client.post("/v1/actions", json=json)
        return SimpleNamespace(ok=response.status_code == 200, status_code=response.status_code, json=response.get_json)

    monkeypatch.setattr("integrations.lite_agent.adapter_executor.requests.post", post)
    params = {"path": str(tmp_path / "guessed.xlsx")}
    response = AdapterExecutor({"libreoffice_calc": "http://synthetic"}).execute(
        "libreoffice_calc", "workbook.read_file", params, {}
    )
    assert response["executed"] is False and response["http_status"] == 404
    assert response["error"]["error"]["details"]["open_documents"] == [observed]
    state = RuntimeState(
        task_id="synthetic-open-workbook", domain="libreoffice_calc",
        instruction="Read the open workbook.",
        events=[ExecutionEvent(
            step=1, timestamp_utc="2026-09-09T00:00:00Z",
            proposed={"kind": "adapter", "action": "workbook.read_file", "arguments": params},
            executed=False, error=response["error"],
        )],
    )
    projected = state.context_summary()
    assert observed["url"] in str(projected)
    assert "FILE_NOT_FOUND" in str(projected)
