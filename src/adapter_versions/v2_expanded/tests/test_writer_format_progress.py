from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from integrations.lite_agent.adapter_results import (
    adapter_context_hint, compact_execution_summary_for_model, execution_context_summary,
)
from integrations.lite_agent.writer_format_progress import writer_format_progress
from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from writer_adapter.text_format import set_text_format
from writer_adapter.text_search import find_text
from test_writer_native_references import FormattingParagraph, formatting_session


IDENTITY = {"url": "file:///tmp/notes.odt", "title": "Notes"}
FORMAT = {"font_size": 11, "italic": True, "bold": False, "script": "normal"}


def match(index, start=0, text="v"):
    return {"paragraph_index": index, "start_offset": start, "end_offset": start + len(text),
            "matched_text": text, "format": deepcopy(FORMAT)}


def event(step, action, args, native, *, forwarded=False, executed=True, error=None):
    body = {"status": "ok", "result": native, "verification": {"passed": True}}
    domain = "libreoffice_writer"
    if forwarded:
        body = {"result": {"adapter": domain, "action": action, "response": body}}
        args = {"adapter": domain, "action": action, "payload": {"params": args}}
        action = "adapter.call"
        domain = "multi_apps"
    hint = adapter_context_hint(domain, action, body)
    return SimpleNamespace(step=step, proposed={"kind": "adapter", "action": action,
        "tool": "adapter__" + action.replace(".", "_"), "arguments": args},
        executed=executed, error=error, result={"context_hint": hint})


def query(step=1, *, rows=None, forwarded=False, more=False, identity=None):
    rows = [match(i) for i in range(3)] if rows is None else rows
    return event(step, "text.find", {"format": {"italic": True}, "max_results": 256}, {
        "identity": IDENTITY if identity is None else identity, "format": {"italic": True},
        "scope": "body_paragraphs", "matches": rows, "returned_count": len(rows),
        "has_more": more,
    }, forwarded=forwarded)


def change(step=2, index=0, *, forwarded=False, identity=None, **options):
    native = {"identity": identity or IDENTITY, "paragraph_index": index,
              "start_offset": 0, "end_offset": 1, "text": "v", "text_unchanged": True,
              "format": {**FORMAT, "font_size": 17.5}}
    native.update(options.pop("native", {}))
    args = {"paragraph_index": index, "start_offset": native["start_offset"],
            "end_offset": native["end_offset"], "expected_text": native["text"], "font_size": 17.5}
    return event(step, "text.set_format", args, native, forwarded=forwarded, **options)


@pytest.mark.parametrize("forwarded", [False, True])
def test_exact_ranges_keep_repeated_text_distinct_and_do_not_count_repeated_calls(forwarded):
    history = [query(forwarded=forwarded), change(forwarded=forwarded),
               change(3, forwarded=forwarded), change(4, 2, forwarded=forwarded)]
    before = deepcopy([vars(e) for e in history])
    progress = writer_format_progress(history, "multi_apps" if forwarded else "libreoffice_writer")
    assert progress["observed_match_count"] == 3
    assert progress["matching_readback_count"] == 2
    assert progress["unconfirmed_count"] == 1
    assert progress["unconfirmed_ranges"][0]["paragraph_index"] == 1
    assert progress["comparison_format"] == {"font_size": 17.5}
    assert [vars(e) for e in history] == before


def test_query_does_not_become_an_edit_requirement_and_partial_queries_stay_partial():
    initial = writer_format_progress([query(more=True)], "libreoffice_writer")
    assert initial["comparison_format"] is None
    assert initial["matching_readback_count"] is None
    assert initial["scope"] == "returned_matches_only"
    assert initial["has_more"] is True
    progress = writer_format_progress([query(more=True), change()], "libreoffice_writer")
    assert progress["matching_readback_count"] == 1
    assert progress["has_more"] is True
    assert "not task completion" in progress["guidance"]


def test_original_matching_formats_are_observations_not_mutation_counts():
    rows = [match(0), match(1)]
    rows[1]["format"]["font_size"] = 17.5
    progress = writer_format_progress([query(rows=rows), change()], "libreoffice_writer")
    assert progress["matching_readback_count"] == 2
    assert progress["unconfirmed_count"] == 0
    assert progress["status"] == "observed_query_only"


@pytest.mark.parametrize("code", ["INVALID_REQUEST", "TEXT_MISMATCH", "TEXT_MATCH_NOT_FOUND"])
def test_rejected_calls_neither_confirm_nor_invalidate_unchanged_observations(code):
    rejected = change(executed=False, error={"error": {"code": code}})
    result = writer_format_progress([query(), rejected, change(3, 1)], "libreoffice_writer")
    assert result["matching_readback_count"] == 1
    assert [r["paragraph_index"] for r in result["unconfirmed_ranges"]] == [0, 2]


@pytest.mark.parametrize("operation", ["text.find_replace", "paragraph.split", "paragraph.set_format"])
def test_untracked_text_or_format_changes_invalidate_and_new_query_recovers(operation):
    mutation = event(3, operation, {}, {"identity": IDENTITY})
    history = [query(), change(), mutation]
    progress = writer_format_progress(history, "libreoffice_writer")
    assert progress["status"] == "invalidated"
    assert "unconfirmed_ranges" not in progress
    recovered = writer_format_progress([*history, query(4)], "libreoffice_writer")
    assert recovered["status"] == "observed_query_only" and recovered["query_step"] == 4
    assert recovered["comparison_format"] is None


@pytest.mark.parametrize("last", [
    SimpleNamespace(step=3, proposed={"kind": "gui", "tool": "gui_action"}, executed=True, result=None),
    change(3, executed=False, error={"error": {"code": "VERIFICATION_FAILED"}}),
    change(3, identity={"url": "file:///tmp/other.odt", "title": "Notes"}),
    change(3, native={"identity": {"title": "Notes"}}),
])
def test_unknown_effects_and_missing_or_different_document_identity_do_not_merge(last):
    progress = writer_format_progress([query(), change(), last], "libreoffice_writer")
    assert progress["status"] == "invalidated"
    assert "matching_readback_count" not in progress


def test_partial_range_readback_cannot_confirm_the_entire_observed_match():
    history = [query(rows=[match(0, text="value")]),
               change(native={"start_offset": 1, "end_offset": 2, "text": "a"})]
    progress = writer_format_progress(history, "libreoffice_writer")
    assert progress["matching_readback_count"] == 0
    assert progress["unconfirmed_ranges"][0]["last_known_format"] is None


def test_document_identity_survives_native_find_and_both_receipt_projections():
    paragraph = FormattingParagraph("alpha X beta X")
    for position in (6, 13):
        paragraph.formats[position]["CharPosture"] = "ITALIC"
    session = formatting_session(paragraph)
    session.doc.URL, session.doc.Title = IDENTITY["url"], IDENTITY["title"]
    found = find_text(session, {"format": {"italic": True}, "max_results": 10})
    assert found["identity"] == IDENTITY
    formatted = set_text_format(session, {"paragraph_index": 0, "start_offset": 6,
        "end_offset": 7, "expected_text": "X", "font_size": 17.5})
    assert formatted["identity"] == IDENTITY
    assert paragraph.String == "alpha X beta X"
    for action in ("text.set_format", "text.set_format_in_match"):
        direct = adapter_context_hint("libreoffice_writer", action, {"result": formatted})
        forwarded = adapter_context_hint("multi_apps", "adapter.call", {"result": {
            "adapter": "libreoffice_writer", "action": action, "response": {"result": formatted}}})
        assert direct["identity"] == forwarded["downstream_context"]["identity"] == IDENTITY


@pytest.mark.parametrize("forwarded", [False, True])
def test_progress_and_unconfirmed_coordinates_survive_history_and_retry_compression(forwarded):
    history = [query(forwarded=forwarded), change(forwarded=forwarded),
               change(3, 2, forwarded=forwarded)]
    for step in range(4, 30):
        history.append(event(step, "document.inspect", {}, {
            "identity": IDENTITY, "paragraphs": ["observed text " * 500]}, forwarded=forwarded))
    summary = execution_context_summary(history, "multi_apps" if forwarded else "libreoffice_writer", limit=1)
    progress = summary[0]["writer_format_progress"]
    assert progress["matching_readback_count"] == 2
    assert progress["unconfirmed_ranges"][0]["paragraph_index"] == 1
    compact = compact_execution_summary_for_model(summary, max_chars=2500)
    assert compact[0]["writer_format_progress"] == progress
    assert len(json.dumps(compact, ensure_ascii=False)) <= 2500


def test_large_queries_have_bounded_remaining_rows_and_honest_omission_counts():
    history = [query(rows=[match(i) for i in range(100)]), change()]
    progress = writer_format_progress(history, "libreoffice_writer")
    assert progress["unconfirmed_count"] == 99
    assert len(progress["unconfirmed_ranges"]) == 8
    assert progress["ranges_omitted_count"] == 91


def test_read_without_identity_invalidates_prior_document_evidence():
    read = event(3, "document.inspect", {}, {"paragraphs": ["unknown document"]})
    progress = writer_format_progress([query(), change(), read], "libreoffice_writer")
    assert progress["status"] == "invalidated"


@pytest.mark.parametrize("forwarded", [False, True])
@pytest.mark.parametrize("recovery", [None, "protocol", "execution"])
def test_progress_reaches_actual_model_messages_with_configured_agent(forwarded, recovery):
    history = [query(forwarded=forwarded), change(forwarded=forwarded),
               change(3, 2, forwarded=forwarded)]
    state = RuntimeState(task_id="synthetic-format-progress",
        domain="multi_apps" if forwarded else "libreoffice_writer",
        instruction="Update the selected italic text size while preserving the body.",
        events=[ExecutionEvent(timestamp_utc="2026-01-01T00:00:00Z", **vars(e)) for e in history])
    original = deepcopy(state.events)
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused.invalid"),
        adapter_executor=None, model_client=SimpleNamespace(client=None))
    messages = agent._messages(state, b"synthetic-image",
        protocol_recovery=recovery == "protocol", execution_recovery=recovery == "execution")
    summary = json.loads(messages[2]["content"][0]["text"].split("\n")[1])
    progress = summary[0]["writer_format_progress"]
    assert progress["observed_match_count"] == 3
    assert progress["matching_readback_count"] == 2
    assert progress["unconfirmed_ranges"][0]["paragraph_index"] == 1
    assert state.events == original
