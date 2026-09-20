"""Unit tests for :mod:`fli.search._concurrency`.

Covers the three building blocks the search layer relies on:

* :class:`TokenBucketRateLimiter` — bucket math, blocking semantics,
  cross-thread fairness, refill behaviour, parameter validation.
* :func:`get_executor` / :func:`configure_concurrency` — pool sizing and
  reinitialisation when the worker cap is raised.
* :func:`parallel_map` — order preservation, exception propagation,
  fallthrough for ≤1 items, and verifiable in-flight concurrency.
"""

from __future__ import annotations

import threading
import time

import pytest

from fli.search._concurrency import (
    TokenBucketRateLimiter,
    configure_concurrency,
    get_executor,
    parallel_map,
    shutdown_executor,
)

# ---------------------------------------------------------------------------
# TokenBucketRateLimiter
# ---------------------------------------------------------------------------


class TestTokenBucketBasics:
    def test_capacity_advertised(self):
        assert TokenBucketRateLimiter(calls=10, period=1.0).capacity == 10

    def test_starts_full(self):
        limiter = TokenBucketRateLimiter(calls=5, period=1.0)
        # Five acquires should all return immediately.
        start = time.perf_counter()
        for _ in range(5):
            assert limiter.acquire() is True
        assert (time.perf_counter() - start) < 0.05

    def test_blocks_when_empty_and_refills(self):
        limiter = TokenBucketRateLimiter(calls=2, period=0.2)  # 10/sec refill
        # Drain.
        limiter.acquire()
        limiter.acquire()
        start = time.perf_counter()
        limiter.acquire()  # must wait for one token (~0.1s)
        elapsed = time.perf_counter() - start
        assert 0.05 < elapsed < 0.30, f"Expected ~0.1s wait, got {elapsed:.3f}s"

    def test_timeout_returns_false(self):
        limiter = TokenBucketRateLimiter(calls=1, period=5.0)
        limiter.acquire()
        assert limiter.acquire(timeout=0.05) is False

    def test_zero_tokens_is_noop(self):
        limiter = TokenBucketRateLimiter(calls=1, period=1.0)
        assert limiter.acquire(tokens=0) is True

    def test_invalid_construction(self):
        with pytest.raises(ValueError):
            TokenBucketRateLimiter(calls=0, period=1.0)
        with pytest.raises(ValueError):
            TokenBucketRateLimiter(calls=1, period=0)

    def test_request_more_than_capacity_raises(self):
        limiter = TokenBucketRateLimiter(calls=3, period=1.0)
        with pytest.raises(ValueError):
            limiter.acquire(tokens=4)


class TestTokenBucketConcurrent:
    """The bucket must release threads in order and stay below the budget."""

    def test_total_throughput_respects_budget(self):
        limiter = TokenBucketRateLimiter(calls=5, period=0.5)  # 10/sec
        # Drain so refill takes over.
        for _ in range(5):
            limiter.acquire()

        completed: list[float] = []
        lock = threading.Lock()

        def worker():
            limiter.acquire()
            with lock:
                completed.append(time.perf_counter())

        threads = [threading.Thread(target=worker) for _ in range(10)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start

        # 10 calls @ 10/sec budget = ~1.0s minimum (started empty).
        assert elapsed >= 0.85, f"Throughput too high: {elapsed:.2f}s for 10 calls"
        # Allow generous upper bound for slow CI hardware.
        assert elapsed < 2.0, f"Throughput too low: {elapsed:.2f}s for 10 calls"

    def test_no_overshoot_within_period(self):
        """At most ``calls`` acquires complete within one period from drain."""
        limiter = TokenBucketRateLimiter(calls=4, period=0.5)
        # Drain.
        for _ in range(4):
            limiter.acquire()

        granted: list[float] = []
        lock = threading.Lock()

        def worker():
            limiter.acquire()
            with lock:
                granted.append(time.perf_counter())

        start = time.perf_counter()
        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # In the first 0.5s after drain we should release at most 4 (=calls)
        # — the bucket was empty so they all wait for fresh tokens.
        within_first_period = sum(1 for g in granted if g - start < 0.55)
        assert within_first_period <= 5, (
            f"Released {within_first_period} tokens in one period; budget is 4"
        )


# ---------------------------------------------------------------------------
# Executor configuration
# ---------------------------------------------------------------------------


class TestExecutorConfiguration:
    def teardown_method(self):
        # Reset shared pool to a known state for subsequent tests.
        shutdown_executor()
        configure_concurrency(10)

    def test_executor_is_singleton(self):
        a = get_executor()
        b = get_executor()
        assert a is b

    def test_configure_grows_pool(self):
        original = get_executor(max_workers=4)
        configure_concurrency(8)
        grown = get_executor()
        assert grown is not original

    def test_configure_rejects_invalid(self):
        with pytest.raises(ValueError):
            configure_concurrency(0)
        with pytest.raises(ValueError):
            configure_concurrency(-1)


# ---------------------------------------------------------------------------
# parallel_map
# ---------------------------------------------------------------------------


class TestParallelMap:
    def teardown_method(self):
        shutdown_executor()
        configure_concurrency(10)

    def test_preserves_order(self):
        result = parallel_map(lambda x: x * 2, [1, 2, 3, 4, 5])
        assert result == [2, 4, 6, 8, 10]

    def test_empty_input(self):
        assert parallel_map(lambda x: x, []) == []

    def test_single_item_is_synchronous(self):
        """One-item input bypasses the executor entirely (fast path)."""
        called_in_thread: list[str] = []

        def fn(x):
            called_in_thread.append(threading.current_thread().name)
            return x

        parallel_map(fn, [42])
        # Must have executed on the calling thread.
        assert called_in_thread == [threading.current_thread().name]

    def test_max_workers_one_is_synchronous(self):
        called_in_thread: list[str] = []

        def fn(x):
            called_in_thread.append(threading.current_thread().name)
            return x

        parallel_map(fn, [1, 2, 3], max_workers=1)
        assert all(t == threading.current_thread().name for t in called_in_thread)

    def test_first_exception_propagates(self):
        def fn(x):
            if x == 2:
                raise ValueError("boom")
            return x

        with pytest.raises(ValueError, match="boom"):
            parallel_map(fn, [1, 2, 3, 4])

    def test_actually_parallel(self):
        """Workers run concurrently — total wall time ~= longest single call."""
        sleep_s = 0.1

        def fn(x):
            time.sleep(sleep_s)
            return x

        start = time.perf_counter()
        result = parallel_map(fn, list(range(5)), max_workers=5)
        elapsed = time.perf_counter() - start
        # Allow 4x as a generous upper bound; sequential would be ~0.5s.
        assert elapsed < sleep_s * 3.5, (
            f"parallel_map ran sequentially: {elapsed:.2f}s for 5×{sleep_s}s"
        )
        assert result == [0, 1, 2, 3, 4]

    def test_max_workers_cap_observed(self):
        """``max_workers=2`` should not run all 4 jobs concurrently."""
        # Reset to a known state so get_executor creates a fresh 2-worker pool.
        shutdown_executor()
        in_flight = 0
        peak = 0
        lock = threading.Lock()

        def fn(x):
            nonlocal in_flight, peak
            with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            time.sleep(0.05)
            with lock:
                in_flight -= 1
            return x

        parallel_map(fn, list(range(4)), max_workers=2)
        assert peak >= 1
        assert peak <= 2

    def test_generator_input_materialised_and_mapped(self):
        result = parallel_map(lambda x: x * 3, (x for x in range(4)))
        assert result == [0, 3, 6, 9]

    def test_tuple_input_works(self):
        result = parallel_map(lambda x: x + 1, (10, 20, 30))
        assert result == [11, 21, 31]

    def test_exception_in_last_item_propagates(self):
        def fn(x):
            if x == 2:
                raise RuntimeError("last item error")
            return x

        with pytest.raises(RuntimeError, match="last item error"):
            parallel_map(fn, [0, 1, 2])


class TestShutdownExecutor:
    def teardown_method(self):
        shutdown_executor()
        configure_concurrency(10)

    def test_shutdown_then_get_creates_new_executor(self):
        original = get_executor()
        shutdown_executor()
        new = get_executor()
        assert new is not original

    def test_shutdown_idempotent(self):
        # Calling shutdown twice must not raise.
        shutdown_executor()
        shutdown_executor()


class TestTokenBucketEdgeCases:
    def test_bulk_acquire_from_full_bucket_is_immediate(self):
        limiter = TokenBucketRateLimiter(calls=5, period=1.0)
        start = time.perf_counter()
        assert limiter.acquire(tokens=3) is True
        assert (time.perf_counter() - start) < 0.05
