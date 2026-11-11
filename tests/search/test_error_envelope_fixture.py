"""A real captured Google Flights error-13 envelope, end to end.

``tests/search/fixtures/flight_search_error13_rejected.txt`` is ported
verbatim (byte-identical, credit to @bjgross10767 / PR #208 for the
capture) from a genuine ``GetBookingResults`` response. It is a
``wrb.fr`` row with a ``null`` payload and a ``type.googleapis.com/
travel.frontend.flights.ErrorResponse`` blob carrying numeric error code
``13`` (INTERNAL) in slot 5 — exactly the shape ``SearchRejectedError``
exists to catch (see ``fli/search/exceptions.py`` and
``fli/search/_wire.py::_chunks_from_outer``).

PR #208 read this capture as a *rate limit* and proposed a 30s-retry
hint. That diagnosis doesn't hold: the gate is Google's now-mandatory
``x-goog-batchexecute-bgr`` header (see issue #223) which a plain HTTP
client can never produce, so the failure is deterministic, not transient
— retrying the exact same request will not succeed. This file locks in
the correct classification instead: parse -> ``SearchRejectedError`` ->
MCP ``error_type == "rejected_error"``, ``retryable == False``.

Fixture contents, checked for anything sensitive: the XSSI prefix
``)]}'``, the ``wrb.fr``/error-code framing described above, three plain
integers that read as Google-internal trace/counters, one short opaque
token (``avU5aqPqKqioj8oP77Xy6Qc``) and one longer opaque token
(``HNWGCqEBKFkQAY0-...``) that are ephemeral per-RPC correlation ids
minted by Google's batchexecute framework for this single anonymous,
unauthenticated request, and trailing ``di``/``af.httprm`` protocol
framing. There is no email, cookie, auth token, IP address, or other
personal data — fli never authenticates to Google Flights, so there is
no account for these ids to identify.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path

import pytest

from fli.core.errors import classify_error
from fli.mcp.server import FlightSearchParams, _execute_booking_options
from fli.models import (
    Airline,
    Airport,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
)
from fli.search import SearchFlights
from fli.search._wire import iter_wrb_chunks
from fli.search.exceptions import SearchRejectedError

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "flight_search_error13_rejected.txt"

# Segment/leg travel dates are validated against today; keep them relative
# so this test doesn't rot as the capture ages (same convention as
# tests/search/test_booking_options.py).
OUT_DATE = (datetime.now() + timedelta(days=30)).date()


@pytest.fixture
def fixture_body() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def _one_way_filters() -> FlightSearchFilters:
    return FlightSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LHR, 0]],
                travel_date=OUT_DATE.isoformat(),
            )
        ],
    )


def _one_way_flight() -> FlightResult:
    leg = FlightLeg(
        airline=Airline.BA,
        flight_number="178",
        departure_airport=Airport.JFK,
        arrival_airport=Airport.LHR,
        departure_datetime=datetime.combine(OUT_DATE, time(18, 0)),
        arrival_datetime=datetime.combine(OUT_DATE, time(6, 30)),
        duration=450,
    )
    return FlightResult(
        legs=[leg],
        price=450.0,
        currency="USD",
        duration=450,
        stops=0,
        # Per-row token captured at parse time — lets get_booking_options
        # resolve a token without a prior search() call / session id.
        booking_token="CAPTURED_ROW_TOKEN",
    )


class _StaticResponse:
    """Stand-in for curl-cffi's response object; always returns the same body."""

    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _StaticClient:
    """Returns the captured envelope for any POST, regardless of payload."""

    def __init__(self, body: str):
        self._body = body

    def post(self, url: str, **kwargs) -> _StaticResponse:
        return _StaticResponse(self._body)


class TestWireLevelParsing:
    """The lowest layer: iter_wrb_chunks must raise, not swallow, this envelope."""

    def test_iter_wrb_chunks_raises_search_rejected_error(self, fixture_body):
        with pytest.raises(SearchRejectedError) as exc_info:
            list(iter_wrb_chunks(fixture_body))
        assert exc_info.value.code == 13

    def test_classify_error_calls_it_rejected_and_not_retryable(self, fixture_body):
        with pytest.raises(SearchRejectedError) as exc_info:
            list(iter_wrb_chunks(fixture_body))
        result = classify_error(exc_info.value)
        assert result.error_type == "rejected_error"
        assert result.retryable is False


class TestSearchFlightsGetBookingOptions:
    """One layer up: the real get_booking_options() call, network mocked only at POST."""

    def test_get_booking_options_raises_search_rejected_error(self, fixture_body):
        search = SearchFlights()
        search.client = _StaticClient(fixture_body)
        filters = _one_way_filters()
        flight = _one_way_flight()

        with pytest.raises(SearchRejectedError) as exc_info:
            search.get_booking_options(flight, filters, currency="USD")
        assert exc_info.value.code == 13


class TestMcpGetBookingOptionsReportsRejectedError:
    """End to end: the MCP tool's response carries the new classification fields."""

    def test_error_type_and_retryable(self, monkeypatch, fixture_body):
        flight = _one_way_flight()
        # Short-circuit the initial shopping search (no network needed for it) —
        # only the booking-options POST should hit the captured envelope.
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", lambda self, *a, **k: [flight])
        monkeypatch.setattr("fli.search.flights.get_client", lambda: _StaticClient(fixture_body))

        params = FlightSearchParams(
            origin="JFK", destination="LHR", departure_date=OUT_DATE.isoformat()
        )
        result = _execute_booking_options(params, None)

        assert result["success"] is False
        assert result["options"] == []  # existing field untouched
        assert "13" in result["error"]  # existing message untouched
        assert result["error_type"] == "rejected_error"
        assert result["retryable"] is False
