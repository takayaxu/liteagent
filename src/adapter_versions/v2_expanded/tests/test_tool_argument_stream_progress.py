from __future__ import annotations

import json

import pytest

from integrations.lite_agent import model_client


def tool_delta(arguments, index=0, name=None):
    return {"index": index, "function": {"name": name, "arguments": arguments}}


class TimedStream:
    def __init__(self, clock, records):
        self.clock = clock
        self.records = records
        self.closed = False
        self.consumed = 0

    def __iter__(self):
        for second, calls, finish in self.records:
            self.clock[0] = second
            self.consumed += 1
            yield {"choices": [{"delta": {"tool_calls": calls}, "finish_reason": finish}]}

    def close(self):
        self.closed = True


@pytest.mark.parametrize("prefix", ['{', '{"text":"kept"}', '{"text":"kept",'])
def test_json_syntax_whitespace_does_not_keep_unterminated_call_alive(monkeypatch, prefix):
    clock = [0.0]
    monkeypatch.setattr(model_client.time, "monotonic", lambda: clock[0])
    stream = TimedStream(clock, [
        (0, [tool_delta(prefix, name="example")], None),
        (100, [tool_delta(" \r\n\t")], None),
        (200, [tool_delta(" \r\n\t")], None),
        (240, [tool_delta(" \r\n\t")], None),
        (300, [], "tool_calls"),
    ])
    with pytest.raises(model_client.StructuredToolProtocolError) as caught:
        model_client._aggregate_stream_response(stream, progress_timeout_seconds=240)
    snapshot = caught.value.response_snapshot
    assert stream.closed and stream.consumed == 4
    assert snapshot["no_progress_seconds"] == 240
    assert snapshot["message"]["tool_calls"] == []
    assert snapshot["partial_tool_calls"][0]["arguments"] == [prefix, " \r\n\t", " \r\n\t"]


@pytest.mark.parametrize("parts", [
    ['{"text":"', " " * 400, " " * 400, '"}'],
    ['{"text":"escaped\\', '"', " " * 400, '"}'],
    ['{"text":"slash\\', '\\', " " * 400, '"}'],
])
def test_string_whitespace_and_split_escapes_remain_progress_and_unchanged(monkeypatch, parts):
    clock = [0.0]
    monkeypatch.setattr(model_client.time, "monotonic", lambda: clock[0])
    stream = TimedStream(clock, [
        (i * 200, [tool_delta(part, name="example" if i == 0 else None)], None)
        for i, part in enumerate(parts)
    ] + [(800, [], "tool_calls")])
    result = model_client._aggregate_stream_response(stream, progress_timeout_seconds=240)
    arguments = result.choices[0].message.tool_calls[0].function.arguments
    assert arguments == "".join(parts)
    assert json.loads(arguments)["text"].endswith(" " * 400)
    assert not stream.closed


def test_each_call_tracks_quotes_even_when_another_call_already_makes_progress(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(model_client.time, "monotonic", lambda: clock[0])
    stream = TimedStream(clock, [
        (0, [tool_delta("{", name="first"), tool_delta('{"text":"', 1, "second")], None),
        (200, [tool_delta(" " * 20, 1)], None),
        (400, [tool_delta(" " * 20, 1)], None),
        (600, [tool_delta('"}', 1), tool_delta("}")], "tool_calls"),
    ])
    result = model_client._aggregate_stream_response(stream, progress_timeout_seconds=240)
    calls = result.choices[0].message.tool_calls
    assert calls[0].function.arguments == "{}"
    assert json.loads(calls[1].function.arguments) == {"text": " " * 40}


def test_only_json_syntax_whitespace_is_ignored_and_validation_still_owns_invalid_json(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(model_client.time, "monotonic", lambda: clock[0])
    stream = TimedStream(clock, [
        (0, [tool_delta("{", name="example")], None),
        (200, [tool_delta("\u00a0")], None),
        (400, [tool_delta("}")], "tool_calls"),
    ])
    result = model_client._aggregate_stream_response(stream, progress_timeout_seconds=240)
    arguments = result.choices[0].message.tool_calls[0].function.arguments
    assert arguments == "{\u00a0}"
    with pytest.raises(json.JSONDecodeError):
        json.loads(arguments)
