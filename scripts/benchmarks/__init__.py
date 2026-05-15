"""Benchmark suite for ``fli`` parsing and concurrency.

Run ``python scripts/benchmarks/bench.py`` to print a side-by-side comparison
of the sequential and parallel code paths on the same hardware. All
benchmarks are deterministic — they replay captured fixtures and mock the
HTTP layer with a controlled-latency stub.
"""
