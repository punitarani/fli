"""Comprehensive ``fli`` parsing & concurrency benchmark suite (30+ scenarios).

Each scenario is deterministic — it replays a real or synthetic fixture
through the same parser code production uses, with HTTP swapped for a
controlled-latency stub. The output is grouped into five sections so
regressions are easy to spot:

1. **Parsing (CPU only)** — scales rows from 1 → 1000 to expose the
   per-row constant factor and any super-linear costs.
2. **Wire-format reading** — single vs multi-chunk responses, the
   currency-token cache, booking decode at multiple vendor counts.
3. **End-to-end search (I/O bound, mocked HTTP)** — one-way at three
   latencies, round-trip across ``top_n`` ∈ {2, 5, 10}, multi-city.
4. **Date-range chunking** — 30 / 90 / 180 / 305-day ranges to verify
   parallelism scales with chunk count.
5. **Concurrency primitives** — bare-metal numbers for
   ``parallel_map`` and ``TokenBucketRateLimiter``.

Usage:

    uv run python scripts/benchmarks/bench.py [--iterations N] [--latency-ms M]
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fli.models import (  # noqa: E402
    Airport,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    TripType,
)
from fli.search import SearchDates, SearchFlights  # noqa: E402
from fli.search._concurrency import (  # noqa: E402
    TokenBucketRateLimiter,
    parallel_map,
)
from fli.search._decoders import parse_booking_chunk, parse_flight_row  # noqa: E402
from fli.search._wire import iter_wrb_chunks, parse_first_wrb_payload  # noqa: E402
from scripts.benchmarks._fixtures import (  # noqa: E402
    synthetic_booking_response,
    synthetic_date_response,
    synthetic_flight_response,
    synthetic_multi_chunk_flight_response,
)
from scripts.benchmarks._harness import (  # noqa: E402
    BenchResult,
    print_table,
    time_callable,
)
from scripts.benchmarks._mocks import FakeClient, load_fixture  # noqa: E402

# ---------------------------------------------------------------------------
# Filter builders
# ---------------------------------------------------------------------------


def _today_plus(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _one_way_filters() -> FlightSearchFilters:
    return FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=_today_plus(30),
            )
        ],
    )


def _round_trip_filters() -> FlightSearchFilters:
    return FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=_today_plus(30),
            ),
            FlightSegment(
                departure_airport=[[Airport.LAX, 0]],
                arrival_airport=[[Airport.JFK, 0]],
                travel_date=_today_plus(37),
            ),
        ],
    )


def _multi_city_filters(n_segments: int) -> FlightSearchFilters:
    cities = [Airport.JFK, Airport.LAX, Airport.SFO, Airport.ORD, Airport.MIA, Airport.BOS]
    segments = []
    for i in range(n_segments):
        dep = cities[i % len(cities)]
        arr = cities[(i + 1) % len(cities)]
        segments.append(
            FlightSegment(
                departure_airport=[[dep, 0]],
                arrival_airport=[[arr, 0]],
                travel_date=_today_plus(30 + i * 5),
            )
        )
    return FlightSearchFilters(
        trip_type=TripType.MULTI_CITY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=segments,
    )


def _date_filters(days: int) -> DateSearchFilters:
    start = _today_plus(7)
    end = (datetime.strptime(start, "%Y-%m-%d") + timedelta(days=days - 1)).strftime("%Y-%m-%d")
    return DateSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=start,
            )
        ],
        from_date=start,
        to_date=end,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rows_from_fixture(fixture: str) -> list:
    inner = parse_first_wrb_payload(fixture)
    if inner is None:
        return []
    return [item for i in (2, 3) if isinstance(inner[i], list) for item in inner[i][0]]


def _wrap(meta: dict, fake: FakeClient) -> dict:
    meta["calls"] = fake.calls
    meta["concurrent_max"] = fake.concurrent_high_water
    return meta


# ---------------------------------------------------------------------------
# Section 1 — Parsing scaling (CPU only)
# ---------------------------------------------------------------------------


def parse_rows_scenario(name: str, rows: list, iterations: int) -> BenchResult:
    def run():
        return [parse_flight_row(r) for r in rows]

    res = time_callable(run, iterations=iterations, name=name)
    res.payload = {"rows": len(rows)}
    return res


def bench_parsing_section(iters: int) -> list[BenchResult]:
    """Cover 1, 10, 50, 200, 1000 row volumes + multi-leg + diverse currencies."""
    results: list[BenchResult] = []

    # Real fixture
    real_body = load_fixture("flight_search_jfk_lax_oneway_usd.bin")
    real_rows = _rows_from_fixture(real_body)
    results.append(parse_rows_scenario("parse 1 row", real_rows[:1], iters * 40))
    results.append(parse_rows_scenario("parse 10 rows", real_rows[:10], iters * 20))
    results.append(parse_rows_scenario("parse 28 rows (real)", real_rows, iters * 10))

    # Synthetic
    syn_50 = _rows_from_fixture(synthetic_flight_response(rows=50))
    syn_200 = _rows_from_fixture(synthetic_flight_response(rows=200))
    syn_1000 = _rows_from_fixture(synthetic_flight_response(rows=1000))
    results.append(parse_rows_scenario("parse 50 rows", syn_50, iters * 4))
    results.append(parse_rows_scenario("parse 200 rows", syn_200, iters * 2))
    results.append(parse_rows_scenario("parse 1000 rows", syn_1000, iters))

    # Multi-leg (layover derivation)
    syn_ml = _rows_from_fixture(synthetic_flight_response(rows=50, multi_leg=True))
    results.append(parse_rows_scenario("parse 50 rows (multi-leg)", syn_ml, iters * 4))

    return results


# ---------------------------------------------------------------------------
# Section 2 — Wire-format reading
# ---------------------------------------------------------------------------


def bench_wire_section(iters: int) -> list[BenchResult]:
    """Wire decoder timings — single / multi chunk and booking parsing."""
    results: list[BenchResult] = []

    real = load_fixture("flight_search_jfk_lax_oneway_usd.bin")
    one_chunk = synthetic_multi_chunk_flight_response(rows_per_chunk=50, chunks=1)
    two_chunk = synthetic_multi_chunk_flight_response(rows_per_chunk=50, chunks=2)
    five_chunk = synthetic_multi_chunk_flight_response(rows_per_chunk=20, chunks=5)

    results.append(
        time_callable(
            lambda: parse_first_wrb_payload(real),
            iterations=iters * 20,
            name="iter_wrb: real 28-row body",
        )
    )
    results.append(
        time_callable(
            lambda: list(iter_wrb_chunks(one_chunk)),
            iterations=iters * 20,
            name="iter_wrb: synthetic 1 chunk",
        )
    )
    results.append(
        time_callable(
            lambda: list(iter_wrb_chunks(two_chunk)),
            iterations=iters * 10,
            name="iter_wrb: synthetic 2 chunks",
        )
    )
    results.append(
        time_callable(
            lambda: list(iter_wrb_chunks(five_chunk)),
            iterations=iters * 10,
            name="iter_wrb: synthetic 5 chunks",
        )
    )

    booking_small = synthetic_booking_response(vendor_count=5)
    booking_large = synthetic_booking_response(vendor_count=50)
    results.append(
        time_callable(
            lambda: parse_booking_chunk(parse_first_wrb_payload(booking_small)),
            iterations=iters * 10,
            name="parse_booking: 5 vendors",
        )
    )
    results.append(
        time_callable(
            lambda: parse_booking_chunk(parse_first_wrb_payload(booking_large)),
            iterations=iters * 5,
            name="parse_booking: 50 vendors",
        )
    )

    return results


# ---------------------------------------------------------------------------
# Section 3 — End-to-end search (mocked HTTP, varying latency)
# ---------------------------------------------------------------------------


def bench_search_section(iters: int) -> list[BenchResult]:
    """End-to-end search wall clock with mocked HTTP at varying latency."""
    fixture = load_fixture("flight_search_jfk_lax_oneway_usd.bin")
    results: list[BenchResult] = []

    def make_one_way(latency_ms: float):
        fake = FakeClient(fixture, latency_ms=latency_ms)

        def run():
            search = SearchFlights()
            search.client = fake
            return search.search(_one_way_filters())

        res = time_callable(run, iterations=iters, name=f"one-way @ {int(latency_ms)}ms")
        res.payload = _wrap({}, fake)
        return res

    def make_round_trip(top_n: int, latency_ms: float = 100.0):
        fake = FakeClient(fixture, latency_ms=latency_ms)

        def run():
            search = SearchFlights()
            search.client = fake
            return search.search(_round_trip_filters(), top_n=top_n)

        res = time_callable(
            run,
            iterations=iters,
            name=f"round-trip top_n={top_n} @ {int(latency_ms)}ms",
        )
        res.payload = _wrap({}, fake)
        return res

    def make_multi_city(n_segments: int, latency_ms: float = 100.0):
        fake = FakeClient(fixture, latency_ms=latency_ms)

        def run():
            search = SearchFlights()
            search.client = fake
            f = _multi_city_filters(n_segments)
            return search.search(f, top_n=3)

        res = time_callable(
            run,
            iterations=iters,
            name=f"multi-city {n_segments}-seg @ {int(latency_ms)}ms",
        )
        res.payload = _wrap({}, fake)
        return res

    results.append(make_one_way(50.0))
    results.append(make_one_way(120.0))
    results.append(make_one_way(500.0))
    results.append(make_round_trip(top_n=2))
    results.append(make_round_trip(top_n=5))
    results.append(make_round_trip(top_n=10))
    results.append(make_multi_city(n_segments=3))

    return results


# ---------------------------------------------------------------------------
# Section 4 — Date-range chunking
# ---------------------------------------------------------------------------


def bench_dates_section(iters: int) -> list[BenchResult]:
    """Date-range searches — chunk count grows linearly with range size."""
    date_body = synthetic_date_response(days=61)
    results: list[BenchResult] = []

    def make(days: int, latency_ms: float = 120.0):
        fake = FakeClient(date_body, latency_ms=latency_ms)

        def run():
            search = SearchDates()
            search.client = fake
            return search.search(deepcopy(_date_filters(days)))

        chunks = (days + 60) // 61
        res = time_callable(
            run,
            iterations=iters,
            name=f"dates {days}d ({chunks} chunks)",
        )
        res.payload = _wrap({}, fake)
        return res

    results.append(make(30))  # 1 chunk
    results.append(make(90))  # 2 chunks
    results.append(make(180))  # 3 chunks
    results.append(make(244))  # 4 chunks
    results.append(make(305))  # 5 chunks (max range)

    return results


# ---------------------------------------------------------------------------
# Section 5 — Concurrency primitives
# ---------------------------------------------------------------------------


def bench_concurrency_section(iters: int) -> list[BenchResult]:
    """Bare-metal numbers for the primitives the search code depends on."""
    results: list[BenchResult] = []

    # parallel_map: small list (5 items, 10ms each)
    def pmap_small():
        return parallel_map(lambda x: time.sleep(0.01) or x, list(range(5)), max_workers=5)

    results.append(time_callable(pmap_small, iterations=iters, name="parallel_map: 5x10ms"))

    # parallel_map: large list (20 items, 5ms each)
    def pmap_large():
        return parallel_map(lambda x: time.sleep(0.005) or x, list(range(20)), max_workers=10)

    results.append(time_callable(pmap_large, iterations=iters, name="parallel_map: 20x5ms"))

    # parallel_map: synchronous fast path
    def pmap_sync():
        return parallel_map(lambda x: x * 2, [42])

    results.append(
        time_callable(pmap_sync, iterations=iters * 100, name="parallel_map: 1 item (sync)")
    )

    # parallel_map: CPU work — token bucket overhead shouldn't matter
    def pmap_cpu():
        return parallel_map(lambda x: sum(range(x)), [10000] * 8, max_workers=4)

    results.append(time_callable(pmap_cpu, iterations=iters, name="parallel_map: 8 CPU jobs"))

    # TokenBucket: uncontended acquire
    bucket_uncon = TokenBucketRateLimiter(calls=1000, period=1.0)
    results.append(
        time_callable(
            lambda: bucket_uncon.acquire(),
            iterations=iters * 200,
            name="bucket acquire (uncontended)",
        )
    )

    # TokenBucket: contended (5 threads sharing 100/sec budget)
    bucket_con = TokenBucketRateLimiter(calls=100, period=1.0)

    def contended():
        threads = []
        for _ in range(5):
            t = threading.Thread(target=lambda: [bucket_con.acquire() for _ in range(4)])
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

    results.append(
        time_callable(contended, iterations=iters, name="bucket: 5 threads x 4 acquires")
    )

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Run all five sections and print a single combined report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--latency-ms",
        type=float,
        default=120.0,
        help="Used wherever a benchmark doesn't fix its own latency.",
    )
    args = parser.parse_args()
    iters = args.iterations
    print(f"Running benchmark suite: {iters} iterations per scenario.\n")

    sections = [
        ("Section 1 — Parsing (CPU)", bench_parsing_section(iters)),
        ("Section 2 — Wire format", bench_wire_section(iters)),
        ("Section 3 — End-to-end search (mocked HTTP)", bench_search_section(iters)),
        ("Section 4 — Date-range chunking", bench_dates_section(iters)),
        ("Section 5 — Concurrency primitives", bench_concurrency_section(iters)),
    ]

    total = sum(len(r) for _, r in sections)
    print(f"Total scenarios: {total}\n")
    for title, results in sections:
        print_table(title, results)

    # Concurrency observations for the search/date sections.
    print("\nObserved request concurrency:")
    for title, results in sections:
        if "Section 3" in title or "Section 4" in title:
            for r in results:
                meta = r.payload or {}
                calls = meta.get("calls", 0) / max(r.iterations, 1)
                peak = meta.get("concurrent_max", 1)
                print(f"  {r.name:40s} calls/run={calls:5.1f} peak in-flight={peak}")

    # Top-level throughput summary.
    print("\nKey throughput metrics:")
    for title, results in sections:
        if "Section 1" in title:
            for r in results:
                rows = (r.payload or {}).get("rows", 0)
                if rows and r.wall_mean > 0:
                    throughput = rows * 1000.0 / r.wall_mean
                    print(f"  {r.name:30s}  {throughput:>12,.0f} rows/sec")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Re-exports for the comparison driver (compare.py).
__all__ = [
    "bench_concurrency_section",
    "bench_dates_section",
    "bench_parsing_section",
    "bench_search_section",
    "bench_wire_section",
]
