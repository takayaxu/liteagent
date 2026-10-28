from types import SimpleNamespace

import jsonschema
import pytest

from integrations.lite_agent.adapter_results import compact_adapter_body
from integrations.lite_agent.atomic_tool_surface import atomic_provider_surface
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools, search_actions
from writer_adapter.errors import AdapterError
from writer_adapter.schema import parse_action_request
from writer_adapter.service import create_app
from writer_adapter.uno_worker import WriterSession


WRITER = "libreoffice_writer"


def _tools(routes):
    return constrain_adapter_call_routes(build_tools(
        "multi_apps", ["adapter.call"], include_gui=False, include_control_tools=False,
        strict_generic=True,
    ), routes)


@pytest.mark.parametrize("surface", ["direct", "wrapper", "atomic", "multiple_writer_routes"])
def test_actual_selector_surfaces_reject_unknown_fields(surface):
    if surface == "direct":
        schema = build_tools(WRITER, ["document.insert_page_break"], include_gui=False,
                             include_control_tools=False)[0]["function"]["parameters"]
        selector = schema["properties"]["document"]
    else:
        routes = [(WRITER, "document.export_pdf")]
        if surface == "multiple_writer_routes":
            routes.append((WRITER, "document.inspect"))
        tools = _tools(routes)
        if surface == "atomic":
            tools, bindings = atomic_provider_surface(tools)
            assert bindings
            schema = tools[0]["function"]["parameters"]
            selector = schema["properties"]["request_options"]["properties"]["document"]
        else:
            schema = tools[0]["function"]["parameters"]
            selector = schema["properties"]["payload"]["properties"]["document"]
    for value in ({}, {"url": "/tmp/source.docx"}, {"title": "source.docx"},
                  {"url": "/tmp/source.docx", "title": "source.docx"}):
        jsonschema.validate(value, selector)
    for value in ({"path": "/tmp/source.docx"}, {"url": ""}, {"title": 5}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(value, selector)


def test_mixed_routes_preserve_other_adapters_document_fields():
    tools = _tools([(WRITER, "document.export_pdf"), ("libreoffice_calc", "workbook.inspect")])
    selector = tools[0]["function"]["parameters"]["properties"]["payload"]["properties"]["document"]
    jsonschema.validate({"other_adapter_field": "observed-value"}, selector)
    assert "adapter=libreoffice_writer" in selector["description"]
    assert "url and/or title" in selector["description"]


def test_bad_selector_is_rejected_before_lifecycle_or_worker_and_feedback_survives():
    # Empty fakes deliberately have no execution methods: validation must fail first.
    client = create_app(lifecycle=SimpleNamespace(), runner=SimpleNamespace()).test_client()
    response = client.post("/v1/actions", json={
        "action": "document.export_pdf", "params": {"path": "/tmp/out.pdf"},
        "document": {"path": "/tmp/source.docx"},
    })
    assert response.status_code == 400
    error = compact_adapter_body(response.get_json())["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["details"] == {"unexpected": ["path"], "allowed": ["url", "title"]}
    assert "document.url" in error["message"]


@pytest.mark.parametrize("selector", [{}, {"url": "/tmp/source.docx"},
                                     {"title": "source.docx"},
                                     {"url": "/tmp/source.docx", "title": "source.docx"}])
def test_valid_document_selection_still_uses_requested_identity(selector, monkeypatch):
    from writer_adapter import uno_worker
    monkeypatch.setattr(uno_worker, "_file_url", lambda value: "file://" + value)
    intended = SimpleNamespace(URL="file:///tmp/source.docx", Title="source.docx")
    other = SimpleNamespace(URL="file:///tmp/other.docx", Title="other.docx")
    session = SimpleNamespace(
        _documents=lambda: [intended, other], identity_for=WriterSession.identity_for,
        desktop=SimpleNamespace(getCurrentComponent=lambda: intended),
    )
    parsed = parse_action_request({"action": "document.inspect", "document": selector})
    assert WriterSession._select_document(session, parsed.document) is intended
    with pytest.raises(AdapterError, match="only document.url"):
        WriterSession._select_document(session, {"path": "/tmp/source.docx"})


def test_zip_creation_description_is_visible_in_discovery_and_actual_tools():
    matches = search_actions("multi_apps", "create ZIP archive from files", limit=7,
                             strict_generic=True)
    result = next(item for item in matches if item.get("downstream_action") == "archive.create_extract")
    assert "mode='create'" in result["description"]
    assert "input_paths" in result["description"]
    tools, bindings = atomic_provider_surface(_tools([("os", "archive.create_extract")]))
    assert bindings
    assert "Create a new ZIP" in tools[0]["function"]["description"]
