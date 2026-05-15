"""Shared timing / reporting helpers for the benchmark suite.

Everything here is deliberately framework-free: no pytest-benchmark, no
external dependencies beyond the standard library. The goal is a
reproducible apples-to-apples wall-clock and CPU-time comparison.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BenchResult:
    """Statistical summary of a single benchmark scenario."""

    name: str
    iterations: int
    wall_ms: list[float] = field(default_factory=list)
    cpu_ms: list[float] = field(default_factory=list)
    payload: Any = None

    @property
    def wall_mean(self) -> float:
        return statistics.mean(self.wall_ms) if self.wall_ms else 0.0

    @property
    def wall_p50(self) -> float:
        return statistics.median(self.wall_ms) if self.wall_ms else 0.0

    @property
    def wall_p95(self) -> float:
        return _percentile(self.wall_ms, 95)

    @property
    def wall_stdev(self) -> float:
        return statistics.stdev(self.wall_ms) if len(self.wall_ms) >= 2 else 0.0

    @property
    def cpu_mean(self) -> float:
        return statistics.mean(self.cpu_ms) if self.cpu_ms else 0.0

    def as_row(self) -> tuple[str, str, str, str, str, str]:
        """Return a tuple ready to drop into a printed table."""
        return (
            self.name,
            f"{self.iterations}",
            f"{self.wall_mean:7.2f}",
            f"{self.wall_p50:7.2f}",
            f"{self.wall_p95:7.2f}",
            f"{self.cpu_mean:7.2f}",
        )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def time_callable(
    fn: Callable[[], Any],
    *,
    iterations: int,
    warmup: int = 1,
    name: str | None = None,
) -> BenchResult:
    """Run ``fn`` ``iterations`` times after ``warmup`` discard runs.

    Returns wall-clock and process CPU time per iteration. The payload of
    the last run is retained so callers can sanity-check the output.
    """
    for _ in range(warmup):
        fn()
    result = BenchResult(name=name or fn.__name__, iterations=iterations)
    payload = None
    for _ in range(iterations):
        t_wall = time.perf_counter()
        t_cpu = time.process_time()
        payload = fn()
        result.wall_ms.append((time.perf_counter() - t_wall) * 1000.0)
        result.cpu_ms.append((time.process_time() - t_cpu) * 1000.0)
    result.payload = payload
    return result


def print_table(title: str, results: list[BenchResult]) -> None:
    """Pretty-print a comparison table grouped under ``title``."""
    header = ("scenario", "iter", "mean ms", "p50 ms", "p95 ms", "cpu ms")
    rows = [r.as_row() for r in results]
    widths = [max(len(header[i]), *(len(row[i]) for row in rows)) for i in range(len(header))]
    print()
    print(title)
    print("-" * len(title))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(header))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))


def speedup(baseline: BenchResult, candidate: BenchResult) -> float:
    """Return baseline / candidate wall-clock mean (>1 means candidate is faster)."""
    if candidate.wall_mean <= 0:
        return float("inf")
    return baseline.wall_mean / candidate.wall_mean
