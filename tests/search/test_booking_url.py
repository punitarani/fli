"""Tests for SearchFlights.build_flight_booking_url.

All tests are purely in-process: no network calls, no live API.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fli.models import Airline, Airport, FlightLeg, FlightResult
from fli.search.flights import SearchFlights

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_leg(
    airline: Airline,
    flight_number: str,
    departure_airport: Airport,
    arrival_airport: Airport,
    dep_date: str,
) -> FlightLeg:
    """Build a minimal FlightLeg with a real departure_datetime."""
    dt = datetime.fromisoformat(f"{dep_date}T08:00:00").replace(tzinfo=timezone.utc)
    return FlightLeg(
        airline=airline,
        flight_number=flight_number,
        departure_airport=departure_airport,
        arrival_airport=arrival_airport,
        departure_datetime=dt,
        arrival_datetime=dt.replace(hour=10),
        duration=120,
    )


def _one_way(airline=Airline.AA, flight_number="1", price=100.0) -> FlightResult:
    return FlightResult(
        price=price,
        duration=120,
        stops=0,
        legs=[_make_leg(airline, flight_number, Airport.SFO, Airport.PHX, "2026-09-01")],
    )


def _round_trip(price=200.0) -> tuple[FlightResult, FlightResult]:
    outbound = FlightResult(
        price=price,
        duration=180,
        stops=0,
        legs=[_make_leg(Airline.AA, "100", Airport.JFK, Airport.LAX, "2026-09-01")],
    )
    inbound = FlightResult(
        price=None,
        duration=180,
        stops=0,
        legs=[_make_leg(Airline.AA, "200", Airport.LAX, Airport.JFK, "2026-09-08")],
    )
    return (outbound, inbound)


def _connection(price=150.0) -> FlightResult:
    dt1 = datetime.fromisoformat("2026-09-01T08:00:00").replace(tzinfo=timezone.utc)
    dt2 = datetime.fromisoformat("2026-09-01T12:00:00").replace(tzinfo=timezone.utc)
    return FlightResult(
        price=price,
        duration=360,
        stops=1,
        legs=[
            FlightLeg(
                airline=Airline.UA,
                flight_number="101",
                departure_airport=Airport.SFO,
                arrival_airport=Airport.ORD,
                departure_datetime=dt1,
                arrival_datetime=dt1.replace(hour=12),
                duration=240,
            ),
            FlightLeg(
                airline=Airline.UA,
                flight_number="202",
                departure_airport=Airport.ORD,
                arrival_airport=Airport.JFK,
                departure_datetime=dt2,
                arrival_datetime=dt2.replace(hour=15),
                duration=120,
            ),
        ],
    )


def _make_client() -> SearchFlights:
    # build_flight_booking_url needs no session id or HTTP client — the tfs
    # token is fully deterministic from the itinerary.
    client = SearchFlights.__new__(SearchFlights)
    client._last_session_id = None
    client.client = MagicMock()
    return client


# ---------------------------------------------------------------------------
# URL structure tests
# ---------------------------------------------------------------------------


class TestBuildFlightBookingUrl:
    def test_one_way_has_tfs(self):
        client = _make_client()
        url = client.build_flight_booking_url(_one_way())
        assert url.startswith("https://www.google.com/travel/flights/booking?tfs=")

    def test_round_trip_has_tfs(self):
        client = _make_client()
        url = client.build_flight_booking_url(_round_trip())
        assert "tfs=" in url

    def test_tfs_no_padding_or_standard_b64(self):
        client = _make_client()
        url = client.build_flight_booking_url(_one_way())
        tfs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["tfs"][0]
        assert "=" not in tfs
        assert "+" not in tfs
        assert "/" not in tfs

    def test_no_tfu_param_emitted(self):
        # tfu adds no value over tfs (tfs-only lands on the specific-flight
        # booking page with vendor fares), so it is never emitted — even when
        # a session id is cached.
        client = _make_client()
        client._last_session_id = "sess123"
        url = client.build_flight_booking_url(_one_way(price=100.0))
        assert "tfu" not in url

    def test_deterministic_same_itinerary_same_url(self):
        # No session id / network state means the same itinerary always yields
        # an identical URL (cacheable, reproducible).
        client = _make_client()
        a = client.build_flight_booking_url(_one_way())
        client._last_session_id = "some-session"
        b = client.build_flight_booking_url(_one_way())
        assert a == b

    def test_locale_params_appended(self):
        client = _make_client()
        url = client.build_flight_booking_url(
            _one_way(), currency="EUR", language="en-GB", country="GB"
        )
        assert "curr=EUR" in url
        assert "hl=en-GB" in url
        assert "gl=GB" in url

    def test_no_locale_params_when_not_provided(self):
        client = _make_client()
        url = client.build_flight_booking_url(_one_way())
        assert "curr=" not in url
        assert "hl=" not in url
        assert "gl=" not in url

    def test_connection_flight_uses_each_leg_in_tfs(self):
        client = _make_client()
        flight = _connection()
        url = client.build_flight_booking_url(flight)
        # Decode tfs and verify both legs are encoded
        import base64

        tfs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["tfs"][0]
        pad = "=" * ((4 - len(tfs) % 4) % 4)
        raw = base64.urlsafe_b64decode(tfs + pad)
        # Both flight numbers and airports should appear in proto bytes
        assert b"101" in raw
        assert b"202" in raw
        assert b"ORD" in raw

    def test_round_trip_two_segments_in_tfs(self):
        client = _make_client()
        import base64

        url = client.build_flight_booking_url(_round_trip())
        tfs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["tfs"][0]
        pad = "=" * ((4 - len(tfs) % 4) % 4)
        raw = base64.urlsafe_b64decode(tfs + pad)
        # f3 field (tag 0x1a = 26) should appear at least twice (two segments)
        assert raw.count(b"\x1a") >= 2

    def test_digit_prefixed_airline_code(self):
        """Frontier (F9 — enum _F9 with underscore prefix) encodes as 'F9'."""
        import base64

        client = _make_client()
        # Use a mock airline with underscore prefix in name to simulate _F9
        mock_leg = MagicMock()
        mock_airline = MagicMock()
        mock_airline.name = "_F9"
        mock_leg.airline = mock_airline
        mock_leg.flight_number = "2638"
        mock_dep = MagicMock()
        mock_dep.name = "SFO"
        mock_arr = MagicMock()
        mock_arr.name = "PHX"
        mock_leg.departure_airport = mock_dep
        mock_leg.arrival_airport = mock_arr
        dep_dt = datetime.fromisoformat("2026-09-01T08:00:00").replace(tzinfo=timezone.utc)
        mock_leg.departure_datetime = dep_dt

        flight = MagicMock()
        flight.legs = [mock_leg]
        flight.price = 89.0
        flight.currency = "USD"

        url = client.build_flight_booking_url(flight)
        tfs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["tfs"][0]
        pad = "=" * ((4 - len(tfs) % 4) % 4)
        raw = base64.urlsafe_b64decode(tfs + pad)
        # Should encode 'F9', not '_F9'
        assert b"F9" in raw
        assert b"_F9" not in raw

    def test_never_raises_on_bad_data(self):
        """Method must not raise even when flight data is malformed."""
        client = _make_client()
        bad_flight = MagicMock()
        bad_flight.legs = [MagicMock(departure_datetime=None)]
        # Should not raise; falls back to a Google Flights URL
        url = client.build_flight_booking_url(bad_flight)
        assert "google.com" in url

    def test_returns_string(self):
        client = _make_client()
        result = client.build_flight_booking_url(_one_way())
        assert isinstance(result, str)
