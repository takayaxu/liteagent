from __future__ import annotations

import pytest

from integrations.lite_agent.model_client import (
    StructuredToolProtocolError,
    _aggregate_stream_response,
)


PERIOD = (
    "The observation establishes a fact, but this hypothesis requires different evidence. " * 9
    + "\n\n"
    + "Reconsidering the same hypothesis without evidence adds no new information. " * 9
    + "\n\n"
)


def chunk(delta, finish=None):
    return {"model": "synthetic", "choices": [{"delta": delta, "finish_reason": finish}]}


class Stream:
    def __init__(self, chunks, close_error=False):
        self.chunks = chunks
        self.closed = False
        self.close_error = close_error
        self.consumed = 0

    def __iter__(self):
        for value in self.chunks:
            self.consumed += 1
            yield value

    def close(self):
        self.closed = True
        if self.close_error:
            raise RuntimeError("synthetic cleanup failure")


@pytest.mark.parametrize("channel", ["reasoning", "reasoning_content"])
@pytest.mark.parametrize("size", [1, 17, 30000])
def test_exact_reasoning_cycles_interrupt_and_preserve_received_evidence(channel, size):
    text = PERIOD * 3
    stream = Stream(
        [chunk({channel: text[i:i + size]}) for i in range(0, len(text), size)]
        + [chunk({channel: "further generation must not be consumed"})],
        close_error=True,
    )
    with pytest.raises(StructuredToolProtocolError) as caught:
        _aggregate_stream_response(stream)
    error = caught.value
    assert error.reason == "reasoning stream repeated without a tool call"
    snapshot = error.response_snapshot
    assert snapshot["client_interrupted"] is True
    assert snapshot["finish_reason"] is None
    assert snapshot["message"][channel] == text
    assert snapshot["message"]["tool_calls"] == []
    assert snapshot["repetition"]["channel"] == channel
    assert snapshot["repetition"]["repetitions"] == 3
    assert snapshot["repetition"]["period_chars"] >= 1024
    assert stream.closed and stream.consumed < len(stream.chunks)


@pytest.mark.parametrize("text", [
    PERIOD * 2 + "A new observation resolves this hypothesis.\n\n",
    "".join(f"New observation {i}: {PERIOD}" for i in range(12)),
    "Short phrase.\n\nOther phrase.\n\n" * 40,
    "One identical long paragraph. " * 60 + "\n\n",
    "```text\n\n" + PERIOD * 5 + "```\n\n",
    "~~~text\n\n" + PERIOD * 5 + "~~~\n\n",
    "```text\n\n" + PERIOD * 5,  # An unclosed fence fails open.
    "\n\n".join("> " + p for p in (PERIOD * 5).split("\n\n")),
    "\n\n".join('"' + p + '"' for p in (PERIOD * 5).split("\n\n")),
    "\n\n".join("    " + p for p in (PERIOD * 5).split("\n\n")),
])
def test_progress_brief_repetition_and_quoted_code_remain_valid(text):
    response = _aggregate_stream_response(Stream([chunk({"reasoning": text})]))
    assert response.choices[0].message.reasoning == text


@pytest.mark.parametrize("delta", [
    {"content": "normal output"},
    {"tool_calls": [{"index": 0, "id": "call", "function": {"name": "example", "arguments": PERIOD * 5}}]},
])
@pytest.mark.parametrize("same_chunk", [True, False])
def test_output_and_arguments_disable_detection_even_in_same_chunk(delta, same_chunk):
    chunks = (
        [chunk({"reasoning": PERIOD * 5, **delta})]
        if same_chunk else [chunk(delta), chunk({"reasoning": PERIOD * 5})]
    )
    result = _aggregate_stream_response(Stream(chunks))
    assert result.choices[0].message.reasoning == PERIOD * 5


@pytest.mark.parametrize("finish", ["length", "tool_calls", "stop"])
def test_terminal_chunk_is_not_reclassified_as_client_interruption(finish):
    result = _aggregate_stream_response(Stream([chunk({"reasoning": PERIOD * 5}, finish)]))
    assert result.choices[0].finish_reason == finish


def test_reasoning_aliases_do_not_combine_into_a_false_cycle():
    result = _aggregate_stream_response(Stream([
        chunk({"reasoning": PERIOD * 2, "reasoning_content": PERIOD * 2}),
    ]))
    assert result.choices[0].message.reasoning_content == PERIOD * 2


@pytest.mark.parametrize("size", [1, 31, 30000])
@pytest.mark.parametrize("text", [
    "“Quoted transcript follows:\n\n" + PERIOD * 4 + "”\n\n",
    '"Quoted transcript follows:\n\n' + PERIOD * 4 + '"\n\n',
    "```text\n\n```not-a-valid-closing-fence\n\n" + PERIOD * 4,
    "````text\n\n```\n\n" + PERIOD * 4,
    "```text\n\n~~~\n\n" + PERIOD * 4,
    "~~~text\n\n~~~not-a-valid-closing-fence\n\n" + PERIOD * 4,
])
def test_ambiguous_quote_and_fence_state_stays_excluded_across_chunks(size, text):
    response = _aggregate_stream_response(Stream([
        chunk({"reasoning": text[i:i + size]}) for i in range(0, len(text), size)
    ]))
    assert response.choices[0].message.reasoning == text


@pytest.mark.parametrize('complete_arguments', [False, True])
def test_empty_tool_chunks_timeout_without_accepting_partial_or_complete_unterminated_call(
    monkeypatch, complete_arguments,
):
    from integrations.lite_agent import model_client
    clock = [0.0]
    monkeypatch.setattr(model_client.time, 'monotonic', lambda: clock[0])
    def chunks():
        yield chunk({'tool_calls': [{'index': 0, 'id': 'call', 'function': {
            'name': 'example', 'arguments': '{}' if complete_arguments else '{'}}]})
        for second in [100, 200, 240, 300]:
            clock[0] = second
            yield chunk({'tool_calls': []})
    stream = Stream(chunks())
    with pytest.raises(StructuredToolProtocolError) as caught:
        _aggregate_stream_response(stream, progress_timeout_seconds=240)
    assert stream.closed
    assert caught.value.response_snapshot['message']['tool_calls'] == []
    assert caught.value.response_snapshot['partial_tool_calls'][0]['name'] == 'example'
    assert caught.value.response_snapshot['no_progress_seconds'] == 240


def test_real_reasoning_and_argument_progress_reset_inactivity_but_empty_chunks_do_not(monkeypatch):
    from integrations.lite_agent import model_client
    clock = [0.0]
    monkeypatch.setattr(model_client.time, 'monotonic', lambda: clock[0])
    def chunks():
        for second, delta, finish in [
            (100, {'reasoning': 'Inspect the source'}, None),
            (300, {'tool_calls': [{'index': 0, 'function': {'name': 'read', 'arguments': '{'}}]}, None),
            (500, {'tool_calls': []}, None),
            (530, {'tool_calls': [{'index': 0, 'function': {'arguments': '}'}}]}, None),
            (760, {}, 'tool_calls'),
        ]:
            clock[0] = second
            yield chunk(delta, finish)
    response = _aggregate_stream_response(Stream(chunks()), progress_timeout_seconds=240)
    assert response.choices[0].message.tool_calls[0].function.arguments == '{}'
    assert response.choices[0].finish_reason == 'tool_calls'


def test_public_client_uses_existing_request_timeout_for_empty_stream_progress(monkeypatch):
    from types import SimpleNamespace
    from integrations.lite_agent import model_client
    clock = [0.0]
    monkeypatch.setattr(model_client.time, 'monotonic', lambda: clock[0])
    def chunks():
        yield chunk({'role': 'assistant'})
        clock[0] = 240
        yield chunk({'tool_calls': []})
    stream = Stream(chunks())
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: stream)))
    client = model_client.StructuredToolModelClient(
        base_url='http://unused/v1', api_key='EMPTY', request_timeout_seconds=240, client=sdk)
    with pytest.raises(StructuredToolProtocolError, match='no semantic progress'):
        client.propose(model='synthetic', messages=[], tools=[], temperature=0,
                       output_token_budget=32, enable_thinking=False)
    assert stream.closed
