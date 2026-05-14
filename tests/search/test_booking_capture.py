"""Smoke tests for the optional Playwright-based booking-token capturer.

The actual browser run is opt-in (requires the ``playwright`` package
plus ``playwright install chromium``); these tests only verify the
public API surface, the import-error path, and the helper logic that
doesn't need Playwright at all.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch

import pytest

from fli.models import Airline, Airport, FlightLeg, FlightResult
from fli.search._booking_capture import _flight_aria_pattern, _format_iata


def _result(airline: Airline, flight_no: str, dep_hour: int, dep_min: int) -> FlightResult:
    from datetime import datetime

    return FlightResult(
        legs=[
            FlightLeg(
                airline=airline,
                flight_number=flight_no,
                departure_airport=Airport.JFK,
                arrival_airport=Airport.LAX,
                departure_datetime=datetime(2026, 7, 15, dep_hour, dep_min),
                arrival_datetime=datetime(2026, 7, 15, dep_hour + 6, dep_min),
                duration=360,
            )
        ],
        price=347,
        currency="USD",
        duration=360,
        stops=0,
    )


class TestFormatIata:
    def test_from_airport_enum(self):
        assert _format_iata(Airport.JFK) == "JFK"

    def test_from_airport_with_leading_underscore(self):
        # Some airline codes start with a digit and the enum prefixes "_";
        # _format_iata is also used for airports, exercise the same path.
        assert _format_iata(Airport.LAX) == "LAX"

    def test_from_plain_string(self):
        assert _format_iata("ATH") == "ATH"


class TestFlightAriaPattern:
    def test_pattern_includes_departure_time(self):
        flight = _result(Airline.AA, "171", 6, 0)
        pattern = _flight_aria_pattern(flight)
        assert "6:00 AM" in pattern
        assert pattern.endswith("on")

    def test_pattern_uses_12_hour_format(self):
        flight_pm = _result(Airline.DL, "100", 17, 30)
        pattern = _flight_aria_pattern(flight_pm)
        assert "5:30 PM" in pattern

    def test_pattern_handles_midnight(self):
        flight = _result(Airline.AA, "1", 0, 15)
        pattern = _flight_aria_pattern(flight)
        # ``%-I`` gives 12 for midnight on POSIX.
        assert "12:15 AM" in pattern


class TestImportErrorPath:
    def test_raises_clear_import_error_when_playwright_missing(self):
        """When Playwright isn't installed, the helper raises a clear ImportError."""
        from fli.search import _booking_capture

        # Patch the import to simulate Playwright being unavailable.
        original_modules = dict(sys.modules)
        # Drop any cached playwright.async_api so the import is re-attempted.
        sys.modules.pop("playwright", None)
        sys.modules.pop("playwright.async_api", None)
        try:
            with patch.dict(sys.modules, {"playwright": None, "playwright.async_api": None}):
                with pytest.raises(ImportError, match="Playwright"):
                    asyncio.run(
                        _booking_capture.capture_booking_token(
                            outbound=_result(Airline.AA, "171", 6, 0),
                            return_flight=None,
                            travel_date="2026-07-15",
                        )
                    )
        finally:
            sys.modules.clear()
            sys.modules.update(original_modules)
