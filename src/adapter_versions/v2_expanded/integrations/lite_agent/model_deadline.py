"""Enforce the episode wall-clock limit across a streaming model request."""

from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
import time


class ModelDeadlineExceeded(TimeoutError):
    """The remaining episode budget expired, regardless of SSE activity."""


def run_before_deadline(create, aggregate, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ModelDeadlineExceeded("episode deadline expired before model request")
    result = Queue(maxsize=1)
    cancelled = Event()
    finished = Event()
    responses = []

    def close(response):
        closer = getattr(response, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    def worker():
        response = None
        try:
            response = create()
            responses.append(response)
            if cancelled.is_set():
                return
            value = aggregate(response)
            if not cancelled.is_set():
                result.put((True, value))
        except BaseException as exc:
            if not cancelled.is_set():
                result.put((False, exc))
        finally:
            if response is not None:
                close(response)
            finished.set()

    # A provider that ignores cancellation must not hold the episode or
    # interpreter open. This worker performs no desktop actions or state edits.
    thread = Thread(target=worker, name="model-episode-deadline", daemon=True)
    thread.start()
    try:
        success, value = result.get(timeout=max(0, deadline - time.monotonic()))
    except Empty:
        cancelled.set()
        # Closing a transport may itself wait on a blocked reader; keep that
        # cleanup outside the deadline-owning runner thread too.
        if responses and not finished.is_set():
            Thread(target=close, args=(responses[0],), daemon=True).start()
        raise ModelDeadlineExceeded(
            "episode deadline expired during streaming model request"
        ) from None
    if time.monotonic() >= deadline:
        cancelled.set()
        raise ModelDeadlineExceeded("model response arrived after episode deadline")
    if not success:
        raise value
    return value
