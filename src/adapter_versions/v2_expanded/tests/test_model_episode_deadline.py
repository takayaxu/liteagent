"""Streaming progress and late responses cannot extend an episode deadline."""

import time
from threading import Event
from types import SimpleNamespace

import pytest

from integrations.lite_agent.model_deadline import (
    ModelDeadlineExceeded,
    run_before_deadline,
)
from integrations.lite_agent.model_client import _aggregate_stream_response


def test_successful_response_and_transport_failure_keep_original_result():
    assert run_before_deadline(lambda: 17, lambda x: x + 1, time.monotonic() + 1) == 18
    error = ValueError("provider failure")

    def fail():
        raise error

    with pytest.raises(ValueError) as caught:
        run_before_deadline(fail, lambda x: x, time.monotonic() + 1)
    assert caught.value is error


def test_expired_budget_never_starts_network_request():
    calls = []
    with pytest.raises(ModelDeadlineExceeded):
        run_before_deadline(lambda: calls.append(1), lambda x: x, time.monotonic() - 1)
    assert calls == []


def test_blocked_initial_response_is_discarded_and_closed_when_it_eventually_arrives():
    release, closed = Event(), Event()

    class Response:
        def close(self):
            closed.set()

    def create():
        release.wait(1)
        return Response()

    started = time.monotonic()
    try:
        with pytest.raises(ModelDeadlineExceeded):
            run_before_deadline(
                create, lambda response: "late-valid-proposal", time.monotonic() + 0.05
            )
        assert time.monotonic() - started < 0.6
    finally:
        release.set()
    assert closed.wait(1)


def test_active_sse_stream_cannot_reset_the_absolute_deadline():
    closed = Event()

    class EndlessStream:
        def __iter__(self):
            while not closed.wait(0.001):
                yield SimpleNamespace(model="synthetic", choices=[])

        def close(self):
            closed.set()

    stream = EndlessStream()
    started = time.monotonic()
    with pytest.raises(ModelDeadlineExceeded):
        run_before_deadline(
            lambda: stream, _aggregate_stream_response, time.monotonic() + 0.05
        )
    assert time.monotonic() - started < 0.6
    assert closed.wait(1)


def test_public_model_client_applies_deadline_before_dispatching_request():
    from integrations.lite_agent.model_client import StructuredToolModelClient

    calls = []
    sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs))
        )
    )
    worker = StructuredToolModelClient(
        base_url="http://unused/v1",
        api_key="EMPTY",
        request_timeout_seconds=1,
        client=sdk,
    )
    with pytest.raises(ModelDeadlineExceeded):
        worker.propose(
            model="synthetic",
            messages=[{"role": "user", "content": "read"}],
            tools=[],
            temperature=0,
            output_token_budget=32,
            enable_thinking=False,
            deadline_monotonic=time.monotonic() - 1,
        )
    assert not calls
