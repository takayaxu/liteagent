from copy import deepcopy
from types import SimpleNamespace

import pytest

from integrations.lite_agent.adapter_results import (
    adapter_context_hint,
    compact_context_hint_for_model,
)
from writer_adapter import uno_worker
from writer_adapter.errors import AdapterError


def session_fixture(monkeypatch, graphic=None, query_error=None, count_added=1):
    calls = []
    image = SimpleNamespace()

    def query(properties):
        calls.append("query")
        if query_error:
            raise query_error
        return graphic

    def create(name):
        calls.append("create")
        return image

    def insert(cursor, actual, absorb):
        assert actual is image and absorb is False
        calls.append("insert")

    text = SimpleNamespace(insertTextContent=insert)
    cursor = SimpleNamespace(getText=lambda: text)
    session = SimpleNamespace(
        doc=SimpleNamespace(createInstance=create),
        context=object(),
        service_manager=SimpleNamespace(
            createInstanceWithContext=lambda name, context: SimpleNamespace(queryGraphic=query)
        ),
        view_cursor=lambda: cursor,
    )
    monkeypatch.setattr(uno_worker, "_file_url", lambda path: "file://" + path)
    monkeypatch.setattr(uno_worker, "_property", lambda name, value: (name, value))
    monkeypatch.setattr(
        uno_worker, "_graphic_object_count",
        lambda doc: count_added if "insert" in calls else 0,
    )
    return session, calls, image


@pytest.mark.parametrize("failure", ["none", "empty", "provider", "type"])
def test_undecodable_input_is_rejected_before_document_mutation(tmp_path, monkeypatch, failure):
    path = tmp_path / "source.png"
    path.write_bytes(b"corrupt or unsupported input")
    graphic = SimpleNamespace(getType=lambda: 0) if failure == "empty" else None
    if failure == "type":
        graphic = SimpleNamespace()  # Missing native type is not proof of decoding.
    session, calls, _ = session_fixture(
        monkeypatch, graphic, RuntimeError("decoder failure") if failure == "provider" else None
    )

    with pytest.raises(AdapterError) as caught:
        uno_worker._insert_image_at_cursor(session, {"path": str(path)})

    assert caught.value.code == "IMAGE_DECODE_FAILED"
    assert caught.value.details == {"path": str(path), "inserted": False}
    assert calls == ["query"]


@pytest.mark.parametrize(("native_type", "kind"), [(1, "bitmap"), (2, "vector")])
def test_native_payload_is_inserted_without_extension_restrictions(tmp_path, monkeypatch, native_type, kind):
    path = tmp_path / "source.unusual"
    path.write_bytes(b"provider-decoded content")
    graphic = SimpleNamespace(getType=lambda: native_type)
    session, calls, image = session_fixture(monkeypatch, graphic)

    result = uno_worker._insert_image_at_cursor(session, {"path": str(path)})

    assert image.Graphic is graphic
    assert not hasattr(image, "GraphicURL")
    assert image.AnchorType == 0
    assert calls == ["query", "create", "insert"]
    assert result["graphic_loaded"] is True
    assert result["graphic_type"] == kind
    assert result["count_verified"] is True


def test_existing_count_check_still_rejects_missing_insertion(tmp_path, monkeypatch):
    path = tmp_path / "source.png"
    path.write_bytes(b"content")
    session, _, _ = session_fixture(monkeypatch, SimpleNamespace(getType=lambda: 1), count_added=0)
    with pytest.raises(AdapterError) as caught:
        uno_worker._insert_image_at_cursor(session, {"path": str(path)})
    assert caught.value.code == "VERIFICATION_FAILED"


def test_missing_file_keeps_not_found_without_query(tmp_path, monkeypatch):
    session, calls, _ = session_fixture(monkeypatch)
    with pytest.raises(AdapterError) as caught:
        uno_worker._insert_image_at_cursor(session, {"path": str(tmp_path / "missing.png")})
    assert caught.value.code == "FILE_NOT_FOUND"
    assert calls == []


@pytest.mark.parametrize("forwarded", [False, True])
def test_loaded_evidence_reaches_model_without_count_only_completion_promise(forwarded):
    result = {"path": "/tmp/image.png", "inserted": True, "graphic_loaded": True,
              "graphic_type": "bitmap", "graphic_objects_added": 1, "count_verified": True,
              "saved": {"exists": True, "valid": True}}
    original = deepcopy(result)
    response = {"status": "ok", "result": result, "verification": {"passed": True}}
    if forwarded:
        response = {"status": "ok", "result": {"adapter": "libreoffice_writer",
                    "action": "image.insert_at_cursor", "response": response}}
    hint = adapter_context_hint("multi_apps" if forwarded else "libreoffice_writer",
                                "adapter.call" if forwarded else "image.insert_at_cursor", response)
    projected = compact_context_hint_for_model(hint, remaining_chars=5000)
    context = projected["downstream_context"] if forwarded else projected
    assert context["graphic_loaded"] is True
    assert context["graphic_type"] == "bitmap"
    assert "not image-content verification" in context["guidance"]
    assert "call propose_done" not in context["guidance"]
    assert result == original
