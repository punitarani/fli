from datetime import date, datetime

import pytest

from fli.models.google_flights import base as _base_models
from fli.models.google_flights import dates as _dates_models


@pytest.fixture
def pin_today(monkeypatch):
    """Return a callable that pins the library's notion of "today".

    Some fixtures — notably the ``tfs`` tokens Google itself issued for a
    specific query — bake in the travel dates they were captured with. Those
    dates cannot be made relative without invalidating the capture, yet the
    filter models refuse a travel date in the past, so the tests would start
    failing the day the capture aged out.

    Pinning the clock instead keeps the goldens byte-exact and makes the
    tests independent of the calendar date the suite runs on. Both modules
    that read the clock are patched: :mod:`fli.models.google_flights.dates`
    imports ``utc_today`` by name, so patching only ``base`` would leave its
    binding pointing at the real clock.

    Usage::

        @pytest.fixture(autouse=True)
        def _clock(pin_today):
            pin_today("2026-08-26")
    """

    def _pin(day: str | date) -> date:
        pinned = day if isinstance(day, date) else datetime.strptime(day, "%Y-%m-%d").date()
        for module in (_base_models, _dates_models):
            monkeypatch.setattr(module, "utc_today", lambda _pinned=pinned: _pinned)
        return pinned

    return _pin


def pytest_addoption(parser) -> None:
    """Add options to pytest."""
    parser.addoption("--fuzz", action="store_true", help="Run fuzz tests")
    parser.addoption("--mcp", action="store_true", help="Run MCP tests")
    parser.addoption("--all", action="store_true", help="Run all tests")
    parser.addoption(
        "--live",
        action="store_true",
        help="Run tests marked 'live' that hit the real Google Flights network",
    )


def pytest_runtest_setup(item) -> None:
    """Skip fuzz tests unless --fuzz or --all is specified; skip live tests unless --live."""
    fuzz_marker = item.get_closest_marker("fuzz")
    if fuzz_marker is not None:
        if not item.config.getoption("--fuzz") and not item.config.getoption("--all"):
            pytest.skip("need --fuzz or --all option to run this test")

    # --all deliberately does NOT imply --live: CI runs with --all, and live
    # tests hit the real network (flaky by nature), so they must opt in
    # separately via --live. See the scheduled live-canary workflow.
    if item.get_closest_marker("live") is not None and not item.config.getoption("--live"):
        pytest.skip("need --live option to run this test (hits the real network)")


def pytest_collection_modifyitems(config, items) -> None:
    """Modify collection based on custom flags."""
    if config.getoption("--mcp"):
        # Only keep MCP tests when --mcp flag is used
        items[:] = [item for item in items if "mcp" in item.nodeid]
    elif config.getoption("--fuzz"):
        # Only keep fuzz tests when --fuzz flag is used (and not --all)
        if not config.getoption("--all"):
            items[:] = [item for item in items if item.get_closest_marker("fuzz")]
    elif not config.getoption("--all"):
        # Remove fuzz tests from normal runs
        items[:] = [item for item in items if not item.get_closest_marker("fuzz")]
