import json

import httpx
import pytest
from openai import OpenAI

from integrations.lite_agent.model_client import _aggregate_stream_response
from integrations.lite_agent.model_transport_trace import ModelTransportTrace


class Stream(httpx.SyncByteStream):
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error
        self.closed = False

    def __iter__(self):
        yield from self.chunks
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


def client(tmp_path, stream):
    trace = ModelTransportTrace(tmp_path)
    return httpx.Client(
        event_hooks=trace.hooks,
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, stream=stream,
            headers={"content-type": "text/event-stream", "cf-ray": "test-ray",
                     "set-cookie": "private-cookie"},
        )),
    )


def records(tmp_path):
    return [json.loads(line) for line in (
        tmp_path / "response_0001/transport.jsonl"
    ).read_text().splitlines()]


def test_partial_stream_survives_original_transport_error_and_secrets_are_excluded(tmp_path):
    error = httpx.RemoteProtocolError("incomplete chunked read")
    partial = b'data: {"choices":[{"delta":{"reasoning":"partial thinking"}}]}\n\n'
    stream = Stream([partial], error)
    with client(tmp_path, stream) as http:
        with pytest.raises(httpx.RemoteProtocolError) as caught:
            with http.stream("POST", "http://unused/v1/chat/completions",
                             headers={"Authorization": "Bearer private-key"}) as response:
                list(response.iter_bytes())
    assert caught.value is error
    assert (tmp_path / "response_0001/body.bin").read_bytes() == partial
    trace = records(tmp_path)
    assert [r["event"] for r in trace] == ["headers", "bytes", "error", "close"]
    assert trace[0]["headers"]["cf-ray"] == "test-ray"
    assert "private" not in json.dumps(trace)
    assert trace[2]["total"] == len(partial)
    assert stream.closed


def test_sdk_receives_identical_tool_call_and_trace_keeps_finish_and_done(tmp_path):
    payload = {"id": "test-id", "model": "synthetic", "choices": [{
        "index": 0, "finish_reason": "tool_calls", "delta": {"tool_calls": [{
            "index": 0, "id": "call-1", "type": "function",
            "function": {"name": "inspect", "arguments": "{}"},
        }]},
    }]}
    body = b'data: ' + json.dumps(payload).encode() + b'\n\ndata: [DONE]\n\n'
    stream = Stream([body[:19], body[19:]])
    with client(tmp_path, stream) as http:
        sdk = OpenAI(base_url="http://unused/v1", api_key="EMPTY", http_client=http)
        result = _aggregate_stream_response(sdk.chat.completions.create(
            model="synthetic", messages=[], stream=True,
        ))
    assert result.choices[0].finish_reason == "tool_calls"
    call = result.choices[0].message.tool_calls[0]
    assert (call.function.name, call.function.arguments) == ("inspect", "{}")
    assert (tmp_path / "response_0001/body.bin").read_bytes() == body
    assert "close" in [r["event"] for r in records(tmp_path)]
    assert "error" not in [r["event"] for r in records(tmp_path)]


def test_early_close_is_not_reported_as_normal_eof(tmp_path):
    stream = Stream([b'first', b'second'])
    with client(tmp_path, stream) as http:
        with http.stream("POST", "http://unused/v1") as response:
            iterator = response.iter_raw()
            assert next(iterator) == b'first'
            response.close()
            iterator.close()
    trace = records(tmp_path)
    assert "close" in [r["event"] for r in trace]
    assert "eof" not in [r["event"] for r in trace]
    assert stream.closed
