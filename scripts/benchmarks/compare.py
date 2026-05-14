"""Before/after comparison driver.

Runs the same scenarios under two implementations: the *parallel* (current
HEAD) implementation, and a *sequential* shim that forces every parallel
path back onto a single thread. This gives apples-to-apples numbers
without needing a separate git checkout.

Usage:

    uv run python scripts/benchmarks/compare.py --iterations 5 --latency-ms 120
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# We toggle "parallel mode" by reaching into the concurrency module and
# forcing the executor to a single worker. ``parallel_map`` falls back to
# a synchronous loop when ``max_workers == 1`` so this perfectly emulates
# the pre-parallelisation behaviour without touching the search code.
import fli.search._concurrency as _conc  # noqa: E402
from scripts.benchmarks._harness import BenchResult, print_table, speedup  # noqa: E402
from scripts.benchmarks._mocks import load_fixture  # noqa: E402
from scripts.benchmarks.bench import (  # noqa: E402
    _extract_rows,
    _synthetic_date_fixture,
    bench_date_range,
    bench_one_way,
    bench_parse_row,
    bench_round_trip,
)


def _set_parallel(enabled: bool) -> None:
    """Toggle between parallel and single-threaded execution."""
    _conc.shutdown_executor()
    _conc.configure_concurrency(10 if enabled else 1)


def _scenario(
    label: str,
    iterations: int,
    latency_ms: float,
    rows,
    fixture,
    date_fixture,
    date_days,
):
    """Build one named bench-result group for either ``seq`` or ``par`` runs."""
    parse = bench_parse_row(rows, iterations=max(iterations * 20, 50))
    one_way = bench_one_way(fixture, iterations, latency_ms)
    round_trip = bench_round_trip(fixture, iterations, latency_ms)
    dates = bench_date_range(date_fixture, iterations, latency_ms, days=date_days)
    parse.name = f"{label}: parse_flight_row (loop)"
    one_way.name = f"{label}: one-way"
    round_trip.name = f"{label}: round-trip top_n=5"
    dates.name = f"{label}: dates {date_days}d"
    return parse, one_way, round_trip, dates


def _summarise(
    title: str,
    seq: tuple[BenchResult, ...],
    par: tuple[BenchResult, ...],
) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    header = ("scenario", "sequential (ms)", "parallel (ms)", "speedup", "saved (ms)")
    rows: list[tuple[str, ...]] = []
    short_names = (
        "parse_flight_row",
        "search one-way",
        "search round-trip",
        "search dates",
    )
    for s, p, name in zip(seq, par, short_names, strict=False):
        sup = speedup(s, p)
        saved = s.wall_mean - p.wall_mean
        rows.append(
            (
                name,
                f"{s.wall_mean:8.2f}",
                f"{p.wall_mean:8.2f}",
                f"{sup:5.2f}x",
                f"{saved:+7.2f}",
            )
        )
    widths = [max(len(header[i]), *(len(row[i]) for row in rows)) for i in range(len(header))]
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(header)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))


def main() -> int:
    """Run the comparison: forced-sequential first, then parallel."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--latency-ms", type=float, default=120.0)
    parser.add_argument("--date-range-days", type=int, default=180)
    args = parser.parse_args()

    fixture = load_fixture("flight_search_jfk_lax_oneway_usd.bin")
    date_fixture = _synthetic_date_fixture(days=61)
    rows = _extract_rows(fixture)

    print(
        f"Comparing sequential vs parallel: latency={args.latency_ms:.0f}ms, "
        f"iters={args.iterations}, rows={len(rows)}, date_range={args.date_range_days}d"
    )

    # Run sequential first so the JIT/cache warms identically for both.
    _set_parallel(False)
    seq = _scenario(
        "seq",
        args.iterations,
        args.latency_ms,
        rows,
        fixture,
        date_fixture,
        args.date_range_days,
    )

    _set_parallel(True)
    par = _scenario(
        "par",
        args.iterations,
        args.latency_ms,
        rows,
        fixture,
        date_fixture,
        args.date_range_days,
    )

    print_table("Raw timings (mean wall-clock ms)", list(seq) + list(par))
    _summarise("Speedup summary", seq, par)

    # Concurrency observations from the parallel run.
    print("\nObserved concurrency (parallel run):")
    for r, name in zip(par[1:], ("one-way", "round-trip top_n=5", "dates"), strict=False):
        meta = r.payload or {}
        per_run = meta.get("calls", 0) / max(r.iterations, 1)
        peak = meta.get("concurrent_max", 1)
        print(f"  {name:25s}  calls/run={per_run:5.1f}  peak in-flight={peak}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
