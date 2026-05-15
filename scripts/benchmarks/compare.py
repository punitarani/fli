"""Sequential-vs-parallel comparison driver across every scenario in ``bench.py``.

Runs each scenario twice — once with the shared executor forced down to a
single worker (so ``parallel_map`` falls back to its synchronous loop),
once with the default capacity — and prints a side-by-side table with
speedup factors.

Scenarios where parallelism makes no difference (pure CPU parsing,
single-chunk wire reads) still appear so we can confirm that the
parallel mode never *regresses* the fast path.

Usage:

    uv run python scripts/benchmarks/compare.py [--iterations N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Force-toggle the shared executor before importing any scenario builders
# so they all see the configured worker cap.
import fli.search._concurrency as _conc  # noqa: E402
from scripts.benchmarks._harness import BenchResult, speedup  # noqa: E402
from scripts.benchmarks.bench import (  # noqa: E402
    bench_concurrency_section,
    bench_dates_section,
    bench_parsing_section,
    bench_search_section,
    bench_wire_section,
)


def _set_parallel(enabled: bool) -> None:
    _conc.shutdown_executor()
    _conc.configure_concurrency(10 if enabled else 1)


def _collect(iters: int) -> dict[str, list[BenchResult]]:
    return {
        "Parsing (CPU)": bench_parsing_section(iters),
        "Wire format": bench_wire_section(iters),
        "End-to-end search": bench_search_section(iters),
        "Date-range chunking": bench_dates_section(iters),
        "Concurrency primitives": bench_concurrency_section(iters),
    }


def _print_section(title: str, seq: list[BenchResult], par: list[BenchResult]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    header = ("scenario", "seq ms", "par ms", "speedup", "saved ms")
    rows: list[tuple[str, ...]] = []
    for s, p in zip(seq, par, strict=False):
        sup = speedup(s, p)
        saved = s.wall_mean - p.wall_mean
        rows.append(
            (
                s.name,
                f"{s.wall_mean:8.2f}",
                f"{p.wall_mean:8.2f}",
                f"{sup:5.2f}x",
                f"{saved:+8.2f}",
            )
        )
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(header)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))


def _print_top_speedups(all_seq: list[BenchResult], all_par: list[BenchResult]) -> None:
    pairs = [(s, p, speedup(s, p)) for s, p in zip(all_seq, all_par, strict=False)]
    pairs.sort(key=lambda x: x[2], reverse=True)
    print("\nTop speedups overall:")
    print("-" * 22)
    for s, p, sup in pairs[:8]:
        print(
            f"  {s.name:45s} {s.wall_mean:7.2f}ms → {p.wall_mean:7.2f}ms  "
            f"({sup:5.2f}x, saved {s.wall_mean - p.wall_mean:+7.2f}ms)"
        )


def main() -> int:
    """Run every scenario in sequential mode, then parallel, then diff."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()

    iters = args.iterations
    print(f"Comparison run: {iters} iterations per scenario, parallel toggled via executor cap.\n")

    _set_parallel(False)
    print("[1/2] Running SEQUENTIAL (max_workers=1)...")
    seq_sections = _collect(iters)

    _set_parallel(True)
    print("[2/2] Running PARALLEL (max_workers=10)...")
    par_sections = _collect(iters)

    flat_seq: list[BenchResult] = []
    flat_par: list[BenchResult] = []
    for title, seq in seq_sections.items():
        par = par_sections[title]
        _print_section(title, seq, par)
        flat_seq.extend(seq)
        flat_par.extend(par)

    _print_top_speedups(flat_seq, flat_par)

    # Quick interpretive summary.
    total_seq = sum(s.wall_mean for s in flat_seq)
    total_par = sum(p.wall_mean for p in flat_par)
    print(
        f"\nAggregate across {len(flat_seq)} scenarios: "
        f"sequential={total_seq:.0f}ms  parallel={total_par:.0f}ms  "
        f"saved={total_seq - total_par:.0f}ms ({total_seq / max(total_par, 1e-6):.2f}x)"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
