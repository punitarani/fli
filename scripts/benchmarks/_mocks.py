"""HTTP mock infrastructure for deterministic concurrency benchmarks.

The fli library talks to Google Flights through a single ``Client`` wrapper
(`fli.search.client.Client`). We swap that out with a controlled-latency
stub so we can measure how well the search code parallelises *its* work,
without actually touching the network or Google's 10 req/sec ceiling.

Each stub method:

* Sleeps for a configurable number of milliseconds (simulated network RTT).
* Returns a pre-baked ``Response``-shaped object whose ``.text`` is one of
  the captured fixtures.
* Increments a thread-safe counter so the benchmark can verify the search
  layer actually issued the expected number of requests.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "search" / "fixtures"


class _FakeResponse:
    """Minimal stand-in for ``curl_cffi.requests.Response``."""

    __slots__ = ("text", "status_code")

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Thread-safe controlled-latency HTTP stub.

    ``post()`` / ``get()`` block for ``latency_ms`` milliseconds and return
    the configured fixture body. The same fixture is returned on every
    call — search logic uses the response shape, not its content, for the
    parts we want to measure.
    """

    def __init__(
        self,
        fixture_text: str,
        *,
        latency_ms: float = 100.0,
    ):
        self._fixture = fixture_text
        self._latency_s = latency_ms / 1000.0
        self._lock = threading.Lock()
        self.calls = 0
        self.concurrent_high_water = 0
        self._in_flight = 0

    def _sleep(self) -> None:
        with self._lock:
            self.calls += 1
            self._in_flight += 1
            if self._in_flight > self.concurrent_high_water:
                self.concurrent_high_water = self._in_flight
        try:
            time.sleep(self._latency_s)
        finally:
            with self._lock:
                self._in_flight -= 1

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self._sleep()
        return _FakeResponse(self._fixture)

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self._sleep()
        return _FakeResponse(self._fixture)


def load_fixture(name: str) -> str:
    """Read a captured response body from ``tests/search/fixtures/``."""
    return (FIXTURE_DIR / name).read_text()
