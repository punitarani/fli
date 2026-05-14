"""Thread-safe concurrency primitives for the search layer.

This module is the single source of truth for how ``fli`` parallelises
work. It exposes three small building blocks:

* :class:`TokenBucketRateLimiter` — a thread-safe token bucket that
  enforces a global "N requests per period" budget. The search code
  acquires one token before every HTTP call so even fully-parallel
  callers stay under Google's 10 req/sec ceiling.

* :func:`get_executor` — a lazily-initialised, module-level
  :class:`~concurrent.futures.ThreadPoolExecutor`. One pool is shared by
  every parallel code path so we never spawn an unbounded number of
  threads when callers nest searches.

* :func:`parallel_map` — a small ``map``-shaped helper that submits
  ``fn(item)`` for each item and returns results in input order. Falls
  back to a sequential loop for trivial inputs (``len ≤ 1`` or
  ``max_workers == 1``) so the fast path stays allocation-free.

Design notes
------------

We deliberately stay on threads, not ``asyncio``. ``curl_cffi`` is a
synchronous client and the rest of the codebase (Pydantic models, the
CLI, the MCP server) is sync too. Threads keep the call sites unchanged
— callers don't need to learn ``await`` — and the heavy lifting in
``json.loads`` releases the GIL, so wall-clock overlap is real even on
CPython.

The rate limiter is the only piece of shared mutable state. It uses a
``threading.Condition`` rather than a ``Semaphore`` because we need the
bucket to *refill* over time, not just count borrowed tokens.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------


class TokenBucketRateLimiter:
    """Thread-safe token bucket — used to enforce a shared request budget.

    The bucket starts full (``capacity`` tokens) and refills continuously
    at ``capacity / period`` tokens per second. :meth:`acquire` returns
    once a token has been taken; concurrent waiters are released as new
    tokens become available, in arrival order.

    Example:
    -------
    >>> limiter = TokenBucketRateLimiter(calls=10, period=1.0)
    >>> limiter.acquire()  # one of 10 tokens this second

    """

    def __init__(self, calls: int, period: float):
        if calls <= 0:
            raise ValueError("calls must be positive")
        if period <= 0:
            raise ValueError("period must be positive")
        self._capacity = float(calls)
        self._refill_per_second = float(calls) / float(period)
        self._tokens = float(calls)
        self._last_refill = time.monotonic()
        self._cv = threading.Condition()

    @property
    def capacity(self) -> int:
        return int(self._capacity)

    def _refill(self) -> None:
        """Advance the bucket's clock and add accrued tokens (caller holds the lock)."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_second)
            self._last_refill = now

    def acquire(self, tokens: int = 1, timeout: float | None = None) -> bool:
        """Block until ``tokens`` are available; return False on timeout.

        ``tokens`` must be ≤ capacity (otherwise the call would never
        return). The wait is fair in practice — :class:`threading.Condition`
        wakes a single waiter at a time and we re-check under the lock.
        """
        if tokens <= 0:
            return True
        if tokens > self._capacity:
            raise ValueError(f"tokens={tokens} exceeds bucket capacity={int(self._capacity)}")

        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    # Wake the next waiter — they may also be ready now.
                    self._cv.notify()
                    return True
                deficit = tokens - self._tokens
                wait_s = deficit / self._refill_per_second
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    wait_s = min(wait_s, remaining)
                # ``wait`` releases the lock and re-acquires on wake.
                self._cv.wait(timeout=wait_s)


# ---------------------------------------------------------------------------
# Shared thread-pool executor
# ---------------------------------------------------------------------------


# Default cap matches Google's 10 req/sec ceiling — we'll never need more
# concurrent HTTP threads than the rate limiter will let through anyway.
_DEFAULT_MAX_WORKERS = 10

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_executor_max_workers: int = _DEFAULT_MAX_WORKERS


def get_executor(max_workers: int | None = None) -> ThreadPoolExecutor:
    """Return the shared :class:`ThreadPoolExecutor`, creating it on first use.

    Re-requesting with a larger ``max_workers`` grows the pool by
    discarding the old executor and starting a new one. This is rare and
    only happens when a user explicitly asks for more parallelism via
    :func:`configure_concurrency`.
    """
    global _executor, _executor_max_workers
    desired = max_workers or _executor_max_workers
    with _executor_lock:
        if _executor is None or desired > _executor_max_workers:
            if _executor is not None:
                _executor.shutdown(wait=False)
            _executor = ThreadPoolExecutor(
                max_workers=desired,
                thread_name_prefix="fli-worker",
            )
            _executor_max_workers = desired
        return _executor


def configure_concurrency(max_workers: int) -> None:
    """Resize the shared executor's worker cap (must be > 0)."""
    if max_workers <= 0:
        raise ValueError("max_workers must be positive")
    global _executor, _executor_max_workers
    with _executor_lock:
        _executor_max_workers = max_workers
        if _executor is not None:
            _executor.shutdown(wait=False)
            _executor = None


def shutdown_executor(wait: bool = True) -> None:
    """Shut down the shared executor (useful in tests)."""
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=wait)
            _executor = None


# ---------------------------------------------------------------------------
# parallel_map — the only helper search code calls directly
# ---------------------------------------------------------------------------


def parallel_map(
    fn: Callable[[T], R],
    items: Iterable[T],
    *,
    max_workers: int | None = None,
) -> list[R]:
    """Apply ``fn`` to each item in parallel; return results in input order.

    The first exception raised by any worker is re-raised here, after the
    remaining in-flight futures have been allowed to complete. We do *not*
    cancel siblings — once submitted, they hold a rate-limit token and
    will release it cleanly when done.

    Falls back to a synchronous loop when the work fits on a single
    thread; this keeps the hot path allocation-free and avoids the
    executor's submit/await overhead for trivial cases.
    """
    materialised: Sequence[T] = list(items) if not isinstance(items, list | tuple) else items
    n = len(materialised)
    if n == 0:
        return []
    workers = max_workers if max_workers is not None else _executor_max_workers
    if n == 1 or workers == 1:
        return [fn(materialised[0])] if n == 1 else [fn(item) for item in materialised]

    executor = get_executor(max_workers=workers)
    futures = [executor.submit(fn, item) for item in materialised]
    results: list[R] = [None] * n  # type: ignore[list-item]
    first_exc: BaseException | None = None
    for idx, fut in enumerate(futures):
        try:
            results[idx] = fut.result()
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            if first_exc is None:
                first_exc = exc
    if first_exc is not None:
        raise first_exc
    return results
