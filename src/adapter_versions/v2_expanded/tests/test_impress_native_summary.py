"""Native summary scope, public parameters, and recoverable partial effects."""
from types import SimpleNamespace

import jsonschema
import pytest

from impress_adapter.errors import AdapterError
from impress_adapter.schema import parse_action_request
from impress_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
from impress_adapter import uno_worker as worker
from integrations.lite_agent.tool_catalog import DIRECT_ACTION_SCHEMAS


ACTION = "slides.create_summary"


def test_scope_contract_is_public_and_dispatched():
    schema = STRICT_ACTION_PARAM_SCHEMAS[ACTION]
    assert DIRECT_ACTION_SCHEMAS["libreoffice_impress"][ACTION] == schema
    assert ACTION in worker.ACTIONS
    for mode, indices in [("selected_slides", [3, 0]), ("from_slide_to_end", [1])]:
        params = {"selection_mode": mode, "slides": indices}
        jsonschema.validate(params, schema)
        assert parse_action_request({"action": ACTION, "params": params}).params == params


@pytest.mark.parametrize("params", [
    {}, {"selection_mode": "selected_slides"},
    {"selection_mode": [], "slides": [0]},
    {"selection_mode": "unknown", "slides": [0]},
    {"selection_mode": "selected_slides", "slides": []},
    {"selection_mode": "selected_slides", "slides": [0, 0]},
    {"selection_mode": "selected_slides", "slides": [True]},
    {"selection_mode": "selected_slides", "slides": [-1]},
    {"selection_mode": "selected_slides", "slides": ["0"]},
    {"selection_mode": "from_slide_to_end", "slides": [0, 1]},
    {"selection_mode": "selected_slides", "slides": [0, 1], "text": "invented"},
])
def test_invalid_parameters_fail_without_opening_or_changing_a_document(params):
    with pytest.raises(AdapterError):
        parse_action_request({"action": ACTION, "params": params})
    with pytest.raises(AdapterError):
        worker._create_summary_slide(None, params)


def _fixture(monkeypatch, *, empty=False, no_output=False, wrong_body=False,
             dispatch_error=False, readback_error=False, already_sorter=False):
    originals = [object() for _ in range(4)]
    pages = list(originals)
    selection = []
    commands = []
    texts = {page: "" if empty else str(i) for i, page in enumerate(originals)}
    anchor = SimpleNamespace(getResourceURL=lambda: "private:resource/pane/CenterPane")
    view = SimpleNamespace(getResourceURL=lambda: "private:resource/view/SlideSorter" if already_sorter
                           else "private:resource/view/ImpressView", getAnchor=lambda: anchor)
    left_anchor = SimpleNamespace(getResourceURL=lambda: "private:resource/pane/LeftImpressPane")
    left_sorter = SimpleNamespace(getResourceURL=lambda: "private:resource/view/SlideSorter",
                                 getAnchor=lambda: left_anchor)
    configuration = SimpleNamespace(getResources=lambda *_: [view, left_sorter])
    def reject_navigation(_):
        pytest.fail("summary must not restore the old current page")

    controller = SimpleNamespace(
        getCurrentPage=lambda: originals[0],
        setCurrentPage=reject_navigation,
        getConfigurationController=lambda: SimpleNamespace(getCurrentConfiguration=lambda: configuration),
        getSelection=lambda: tuple(page for page in originals if page in selection),
    )
    session = SimpleNamespace(
        pages=SimpleNamespace(getCount=lambda: len(pages), getByIndex=pages.__getitem__),
        doc=SimpleNamespace(getCurrentController=lambda: controller),
    )

    def dispatch(_, command):
        commands.append(command)
        if command == ".uno:SummaryPage" and not no_output:
            new = object()
            pages.append(new)
            selected = [i for i, page in enumerate(originals) if page in selection]
            effective = list(range(selected[0], len(originals))) if len(selected) == 1 else selected
            texts[new] = "0\n1\n3" if wrong_body else "\n".join(texts[originals[i]] for i in effective if texts[originals[i]] != "")
            if dispatch_error:
                raise RuntimeError("dispatch failed after a partial effect")
        if command not in {".uno:DiaMode", ".uno:SummaryPage"}:
            pytest.fail("summary must not restore or otherwise switch views after dispatch")

    def inspect(_, index):
        if readback_error and index >= len(originals):
            raise RuntimeError("new page readback failed")
        return {"index": index, "notes": "original notes", "shapes": [
            {"kind": "com.sun.star.presentation.TitleTextShape" if index < len(originals)
             else "com.sun.star.presentation.OutlinerShape", "text": texts[pages[index]],
             "graphic_fingerprint": "observed image evidence"}]}

    uno = SimpleNamespace(
        Enum=lambda *_: None,
        Any=lambda _, value: value,
        invoke=lambda _controller, _method, args: selection.extend(args[0]),
    )
    monkeypatch.setattr(worker, "_uno_modules", lambda: (uno, None))
    monkeypatch.setattr(worker, "_dispatch", dispatch)
    monkeypatch.setattr(worker, "_page_summary", inspect)
    return session, commands, pages, originals


@pytest.mark.parametrize("mode,indices,effective,body", [
    ("selected_slides", [3, 0], [0, 3], "0\n3"),
    ("selected_slides", [0, 3], [0, 3], "0\n3"),
    ("selected_slides", [3], [3], "3"),
    ("from_slide_to_end", [1], [1, 2, 3], "1\n2\n3"),
])
def test_native_call_is_once_with_explicit_scope_and_actual_readback(monkeypatch, mode, indices, effective, body):
    session, commands, pages, originals = _fixture(monkeypatch)
    result = worker._create_summary_slide(session, {"selection_mode": mode, "slides": indices})
    assert commands.count(".uno:SummaryPage") == 1
    assert commands == [".uno:DiaMode", ".uno:SummaryPage"]
    assert result["view_restored"] is False
    assert result["effective_source_slides"] == effective
    assert result["created_slide_indices"] == [4]
    assert result["native_summary_bodies"] == [body]
    assert result["observed_selected_slides"] == sorted(indices)
    assert result["native_selection_order"] == sorted(indices, reverse=True)
    assert result["source_titles_match"] is True
    assert result["source_preservation"]["page_summary_unchanged"]
    assert result["saved"] is False
    assert pages[:4] == originals


def test_existing_central_sorter_needs_no_view_switch(monkeypatch):
    session, commands, _, _ = _fixture(monkeypatch, already_sorter=True)
    result = worker._create_summary_slide(session, {"selection_mode": "selected_slides", "slides": [0, 3]})
    assert commands == [".uno:SummaryPage"]
    assert result["source_titles_match"] is True


@pytest.mark.parametrize("indices", [[1], [4], [0, 8]])
def test_live_scope_rejected_before_any_view_or_selection_change(monkeypatch, indices):
    session, commands, pages, originals = _fixture(monkeypatch)
    with pytest.raises(AdapterError):
        worker._create_summary_slide(session, {"selection_mode": "selected_slides", "slides": indices})
    assert commands == []
    assert pages == originals


def test_all_empty_native_titles_remain_an_explicit_empty_result(monkeypatch):
    session, _, _, _ = _fixture(monkeypatch, empty=True)
    result = worker._create_summary_slide(session, {"selection_mode": "selected_slides", "slides": [0, 1]})
    assert result["summary_empty"] is True
    assert result["native_summary_bodies"] == [""]


def test_whitespace_title_remains_nonempty(monkeypatch):
    session, _, _, _ = _fixture(monkeypatch)
    inspect = worker._page_summary
    monkeypatch.setattr(worker, "_page_summary", lambda session, index: {
        **inspect(session, index), "shapes": [{
            "kind": "com.sun.star.presentation.TitleTextShape" if index < 4
            else "com.sun.star.presentation.OutlinerShape", "text": " "}]})
    result = worker._create_summary_slide(session, {"selection_mode": "selected_slides", "slides": [3]})
    assert result["summary_empty"] is False
    assert result["native_summary_bodies"] == [" "]


def test_multiple_native_titles_rejected_before_dispatch(monkeypatch):
    session, commands, pages, originals = _fixture(monkeypatch)
    inspect = worker._page_summary
    monkeypatch.setattr(worker, "_page_summary", lambda session, index: {
        **inspect(session, index), "shapes": inspect(session, index)["shapes"] * 2})
    with pytest.raises(AdapterError) as caught:
        worker._create_summary_slide(session, {"selection_mode": "selected_slides", "slides": [0, 3]})
    assert caught.value.code == "UNSUPPORTED_OPERATION"
    assert commands == []
    assert pages == originals


@pytest.mark.parametrize("option,created", [
    ("no_output", []), ("wrong_body", [4]),
    ("dispatch_error", [4]), ("readback_error", [4]),
])
def test_partial_or_unverified_execution_is_reported_without_retry(monkeypatch, option, created):
    session, commands, _, _ = _fixture(monkeypatch, **{option: True})
    with pytest.raises(AdapterError) as caught:
        worker._create_summary_slide(session, {"selection_mode": "selected_slides", "slides": [0, 1]})
    assert caught.value.code == "SUMMARY_CREATION_FAILED"
    assert caught.value.details["created_slide_indices"] == created
    assert caught.value.details["partial_effects_possible"] is True
    assert commands.count(".uno:SummaryPage") == 1
