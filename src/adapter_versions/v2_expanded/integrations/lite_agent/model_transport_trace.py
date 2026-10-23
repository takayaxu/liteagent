"""Observe HTTP response bytes without changing model requests or stream handling.

Each response gets raw body bytes and a timestamped ledger. These diagnostics
are host artifacts only and are never fed into the agent's model context.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
import time

import httpx


RESPONSE_HEADERS = frozenset({
    "server", "date", "content-type", "content-length", "transfer-encoding",
    "content-encoding", "connection", "cf-ray", "x-request-id", "via",
    "x-accel-buffering",
})


class ModelTransportTrace:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.count = 0
        self.lock = Lock()

    def request(self, request):
        request.extensions["liteagent_trace_start"] = time.monotonic()

    def response(self, response):
        with self.lock:
            self.count += 1
            directory = self.directory / f"response_{self.count:04d}"
            directory.mkdir(exist_ok=False)
        started = response.request.extensions.get("liteagent_trace_start", time.monotonic())
        stream = _TracedStream(response.stream, directory, started)
        stream.record(
            "headers", status=response.status_code, http_version=response.http_version,
            headers={k: v for k, v in response.headers.items() if k in RESPONSE_HEADERS},
        )
        response.stream = stream

    @property
    def hooks(self):
        return {"request": [self.request], "response": [self.response]}


class _TracedStream(httpx.SyncByteStream):
    def __init__(self, stream, directory, started):
        self.stream = stream
        self.started = started
        self.ledger = directory / "transport.jsonl"
        self.body = directory / "body.bin"
        self.total = 0
        self.lock = Lock()

    def record(self, event, **fields):
        record = {
            "event": event,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - self.started, 6),
            **fields,
        }
        with self.lock, self.ledger.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")

    def __iter__(self):
        try:
            with self.body.open("xb") as output:
                for chunk in self.stream:
                    output.write(chunk)
                    output.flush()
                    self.total += len(chunk)
                    self.record("bytes", count=len(chunk), total=self.total)
                    yield chunk
            self.record("eof", total=self.total)
        except GeneratorExit:
            # The SDK normally stops consuming at SSE [DONE], before HTTP EOF.
            self.record("iterator_closed", total=self.total)
            raise
        except BaseException as exc:
            self.record("error", type=type(exc).__name__, detail=str(exc), total=self.total)
            raise

    def close(self):
        try:
            self.stream.close()
        finally:
            self.record("close", total=self.total)
