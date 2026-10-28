from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from calc_adapter import uno_worker
from calc_adapter.errors import AdapterError
from calc_adapter.service import create_app
from calc_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS as CALC_SCHEMAS
from integrations.lite_agent.adapter_executor import AdapterExecutor
from integrations.lite_agent.adapter_results import spreadsheet_file_context
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools, search_actions
from os_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS as OS_SCHEMAS


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


@pytest.mark.parametrize("query", [
    "open LibreOffice Calc file",
    "libreoffice calc open file",
    "open spreadsheet xlsx file",
])
def test_opening_a_spreadsheet_file_exposes_desktop_open_path(query):
    assert ("os", "desktop.open_path") in routes(query)[:5]
    assert ("libreoffice_calc", "workbook.inspect") in routes(
        "inspect current open Calc workbook"
    )[:3]


def test_spreadsheet_open_and_file_preview_contracts_distinguish_live_document():
    opening = OS_SCHEMAS["desktop.open_path"]["description"]
    preview = CALC_SCHEMAS["workbook.read_file"]["description"]
    assert "registered desktop application" in opening
    assert "Launch success alone does not prove" in opening
    assert "temporary read-only preview" in preview
    assert "does not leave a live Calc workbook" in preview


def test_file_preview_addresses_align_with_display_and_bound_truncation():
    result = {
        "path": "/tmp/table.xlsx",
        "url": "file:///tmp/table.xlsx",
        "format": "xlsx",
        "sheet_count": 1,
        "returned_sheet_count": 1,
        "sheets_truncated": False,
        "truncated": False,
        "sheets": [{
            "name": "Week",
            "used_range": "A1:D200",
            "source_range": "A1:D200",
            "returned_range": "A1:D200",
            "source_rows": 200,
            "source_columns": 4,
            "returned_rows": 200,
            "returned_columns": 4,
            "truncated": False,
            "display_text": [["", "Alpha", "Beta", "Gamma"]] + [
                [str(i), "", "", ""] for i in range(2, 201)
            ],
        }],
    }
    context = spreadsheet_file_context(result)
    sheet = context["sheets"][0]
    assert context["read_only_preview"] is True
    assert "desktop.open_path" in context["guidance"]
    assert sheet["cell_addresses"][0] == ["A1", "B1", "C1", "D1"]
    assert sheet["display_text"][0][3] == "Gamma"
    assert sheet["rows_omitted_from_context"] > 0
    assert len(sheet["cell_addresses"]) == len(sheet["display_text"])
    assert all(len(a) == len(v) for a, v in zip(
        sheet["cell_addresses"], sheet["display_text"]
    ))


def test_missing_live_calc_document_explains_how_to_open_observed_file():
    session = object.__new__(uno_worker.CalcSession)
    session._documents = lambda: []
    with pytest.raises(AdapterError) as failure:
        session._select_document({})
    assert failure.value.code == "NO_CALC_DOCUMENT"
    assert "workbook.read_file preview" in failure.value.message
    assert "os.desktop.open_path" in failure.value.message


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
