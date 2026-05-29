"""Unit tests for MCP server serialization helpers and error propagation.

Targets functions that are only reached via integration tests in the existing
suite: _airline_code, _serialize_flight_leg, _serialize_layover,
_flight_extras, and the bare-except error path in _execute_flight_search.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fli.mcp.server import (
    FlightSearchParams,
    _airline_code,
    _execute_booking_options,
    _execute_flight_search,
    _flight_extras,
    _google_flights_url,
    _match_flight,
    _serialize_booking_option,
    _serialize_date_result,
    _serialize_flight_leg,
    _serialize_layover,
)


def _make_raiser(exc: BaseException):
    """Return a callable that unconditionally raises ``exc``."""

    def _raiser(*args, **kwargs):
        raise exc

    return _raiser


class TestAirlineCode:
    def test_enum_with_leading_underscore_stripped(self):
        airline = MagicMock()
        airline.name = "_2B"
        assert _airline_code(airline) == "2B"

    def test_plain_enum_name_unchanged(self):
        airline = MagicMock()
        airline.name = "DL"
        assert _airline_code(airline) == "DL"

    def test_plain_string_passthrough(self):
        # Strings have no `.name` attribute, so str(airline) is used.
        assert _airline_code("AA") == "AA"


class TestSerializeFlightLeg:
    def _make_leg(self, **overrides):
        leg = MagicMock()
        leg.departure_airport = "JFK"
        leg.arrival_airport = "LHR"
        leg.departure_datetime = None
        leg.arrival_datetime = None
        leg.duration = 420
        leg.airline = "AA"
        leg.flight_number = "100"
        leg.departure_airport_name = None
        leg.arrival_airport_name = None
        leg.operating_airline = None
        leg.aircraft = None
        leg.legroom = None
        leg.overnight = False
        leg.amenities = None
        for k, v in overrides.items():
            setattr(leg, k, v)
        return leg

    def test_required_fields_always_present(self):
        leg = self._make_leg()
        result = _serialize_flight_leg(leg)
        for key in (
            "departure_airport",
            "arrival_airport",
            "departure_time",
            "arrival_time",
            "duration",
            "airline",
            "airline_code",
            "flight_number",
        ):
            assert key in result

    def test_none_optional_fields_excluded(self):
        leg = self._make_leg()
        result = _serialize_flight_leg(leg)
        assert "departure_airport_name" not in result
        assert "arrival_airport_name" not in result
        assert "operating_airline" not in result
        assert "aircraft" not in result
        assert "legroom" not in result

    def test_overnight_true_included(self):
        leg = self._make_leg(overnight=True)
        result = _serialize_flight_leg(leg)
        assert result.get("overnight") is True

    def test_overnight_false_excluded(self):
        leg = self._make_leg(overnight=False)
        result = _serialize_flight_leg(leg)
        assert "overnight" not in result

    def test_operating_airline_included_when_set(self):
        op = MagicMock()
        op.name = "B6"
        leg = self._make_leg(operating_airline=op)
        result = _serialize_flight_leg(leg)
        assert result["operating_airline"] == "B6"

    def test_amenities_included_with_truthy_fields(self):
        from fli.models import Amenities

        leg = self._make_leg(amenities=Amenities(wifi=True))
        result = _serialize_flight_leg(leg)
        assert "amenities" in result
        assert result["amenities"]["wifi"] is True

    def test_amenities_excluded_when_none(self):
        leg = self._make_leg(amenities=None)
        result = _serialize_flight_leg(leg)
        assert "amenities" not in result

    def test_amenities_excluded_when_all_fields_are_none(self):
        from fli.models import Amenities

        leg = self._make_leg(amenities=Amenities())
        result = _serialize_flight_leg(leg)
        # model_dump(exclude_none=True) on an all-None Amenities → empty dict → not included
        assert "amenities" not in result


class TestSerializeLayover:
    def _make_layover(self, **overrides):
        lo = MagicMock()
        lo.airport = "FRA"
        lo.duration = 90
        lo.overnight = False
        lo.change_of_airport = False
        for k, v in overrides.items():
            setattr(lo, k, v)
        return lo

    def test_airport_and_duration_always_present(self):
        lo = self._make_layover()
        result = _serialize_layover(lo)
        assert "airport" in result
        assert result["duration"] == 90

    def test_overnight_true_included(self):
        lo = self._make_layover(overnight=True)
        result = _serialize_layover(lo)
        assert result.get("overnight") is True

    def test_overnight_false_excluded(self):
        lo = self._make_layover(overnight=False)
        result = _serialize_layover(lo)
        assert "overnight" not in result

    def test_change_of_airport_true_included(self):
        lo = self._make_layover(change_of_airport=True)
        result = _serialize_layover(lo)
        assert result.get("change_of_airport") is True

    def test_change_of_airport_false_excluded(self):
        lo = self._make_layover(change_of_airport=False)
        result = _serialize_layover(lo)
        assert "change_of_airport" not in result


class TestFlightExtras:
    def _make_flight(self, **overrides):
        f = MagicMock()
        f.primary_airline_name = None
        f.self_transfer = None
        f.mixed_cabin = None
        f.primary_airline = None
        f.layovers = None
        for k, v in overrides.items():
            setattr(f, k, v)
        return f

    def test_booking_token_not_surfaced(self):
        # booking_token is an internal artifact no MCP tool consumes; it must
        # never appear in the response shape even when the parser populates it.
        f = self._make_flight(booking_token="tok123")
        result = _flight_extras(f)
        assert "booking_token" not in result

    def test_self_transfer_true_included(self):
        f = self._make_flight(self_transfer=True)
        result = _flight_extras(f)
        assert result.get("self_transfer") is True

    def test_layovers_serialized(self):
        lo = MagicMock()
        lo.airport = "CDG"
        lo.duration = 60
        lo.overnight = False
        lo.change_of_airport = False
        f = self._make_flight(layovers=[lo])
        result = _flight_extras(f)
        assert "layovers" in result
        assert len(result["layovers"]) == 1


class TestExecuteFlightSearchNetworkError:
    """The bare-except in _execute_flight_search must produce a clean error dict."""

    @pytest.fixture
    def valid_params(self):
        return FlightSearchParams(
            origin="JFK",
            destination="LHR",
            departure_date="2026-12-01",
        )

    def test_search_client_error_returns_success_false(self, monkeypatch, valid_params):
        from fli.search.exceptions import SearchClientError

        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            _make_raiser(SearchClientError("network down")),
        )
        result = _execute_flight_search(valid_params)
        assert result["success"] is False

    def test_exception_message_in_error_field(self, monkeypatch, valid_params):
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            _make_raiser(RuntimeError("proxy timeout")),
        )
        result = _execute_flight_search(valid_params)
        assert result["error"] == "Search failed: proxy timeout"

    def test_flights_key_is_empty_list_on_error(self, monkeypatch, valid_params):
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            _make_raiser(RuntimeError("fail")),
        )
        result = _execute_flight_search(valid_params)
        assert result["flights"] == []


def _make_bookable_leg(code="BA", number="178"):
    """Build a flight leg mock with optional fields set to None for clean serialization."""
    leg = MagicMock()
    airline = MagicMock()
    airline.name = code
    leg.airline = airline
    leg.flight_number = number
    leg.departure_airport = "JFK"
    leg.arrival_airport = "LHR"
    leg.departure_datetime = None
    leg.arrival_datetime = None
    leg.duration = 420
    leg.departure_airport_name = None
    leg.arrival_airport_name = None
    leg.operating_airline = None
    leg.aircraft = None
    leg.legroom = None
    leg.overnight = False
    leg.amenities = None
    return leg


def _make_bookable_flight(legs=None, price=342.0):
    flight = MagicMock()
    flight.legs = legs or [_make_bookable_leg()]
    flight.price = price
    flight.currency = "USD"
    flight.layovers = None
    flight.primary_airline = None
    flight.primary_airline_name = None
    flight.self_transfer = None
    flight.mixed_cabin = None
    flight.booking_token = "tok"
    return flight


def _make_option_helper():
    opt = MagicMock()
    opt.vendor_name = "American Airlines"
    opt.vendor_code = "AA"
    opt.fare_name = "Main Cabin"
    opt.currency = "USD"
    opt.booking_url = "https://book.aa.com/x"
    opt.google_click_url = "https://www.google.com/x"
    opt.price = 342.0
    opt.is_airline_direct = True
    return opt


class TestGoogleFlightsUrl:
    def _url(self, **kwargs):
        from fli.models import Airport

        defaults = {
            "origins": [Airport.JFK],
            "destinations": [Airport.LHR],
            "departure_date": "2026-12-01",
            "return_date": None,
            "currency": None,
            "language": None,
            "country": None,
        }
        defaults.update(kwargs)
        return _google_flights_url(
            defaults["origins"],
            defaults["destinations"],
            defaults["departure_date"],
            defaults["return_date"],
            defaults["currency"],
            defaults["language"],
            defaults["country"],
        )

    def test_one_way_contains_route_and_date(self):
        url = self._url()
        assert url.startswith("https://www.google.com/travel/flights?q=")
        assert "JFK" in url
        assert "LHR" in url
        assert "2026-12-01" in url

    def test_round_trip_includes_return_date(self):
        url = self._url(return_date="2026-12-10")
        assert "2026-12-10" in url

    def test_locale_params_appended(self):
        url = self._url(currency="EUR", language="en-GB", country="GB")
        assert "curr=EUR" in url
        assert "hl=en-GB" in url
        assert "gl=GB" in url

    def test_uses_first_airport_when_multiple(self):
        from fli.models import Airport

        url = self._url(origins=[Airport.JFK, Airport.LGA], destinations=[Airport.LHR])
        assert "JFK" in url
        assert "LGA" not in url


class TestMatchFlight:
    def test_match_by_bare_number(self):
        flight = _make_bookable_flight(legs=[_make_bookable_leg("BA", "178")])
        assert _match_flight([flight], ["178"]) is flight

    def test_match_by_airline_prefixed(self):
        flight = _make_bookable_flight(legs=[_make_bookable_leg("BA", "178")])
        assert _match_flight([flight], ["BA178"]) is flight

    def test_match_is_case_insensitive(self):
        flight = _make_bookable_flight(legs=[_make_bookable_leg("BA", "178")])
        assert _match_flight([flight], ["ba178"]) is flight

    def test_no_match_returns_none(self):
        flight = _make_bookable_flight(legs=[_make_bookable_leg("BA", "178")])
        assert _match_flight([flight], ["ZZ999"]) is None

    def test_none_defaults_to_first(self):
        first = _make_bookable_flight(legs=[_make_bookable_leg("BA", "1")])
        second = _make_bookable_flight(legs=[_make_bookable_leg("AA", "2")])
        assert _match_flight([first, second], None) is first

    def test_round_trip_tuple_matched_in_order(self):
        outbound = _make_bookable_flight(legs=[_make_bookable_leg("AA", "100")])
        inbound = _make_bookable_flight(legs=[_make_bookable_leg("AA", "200")])
        combo = (outbound, inbound)
        assert _match_flight([combo], ["AA100", "AA200"]) is combo

    def test_wrong_leg_count_does_not_match(self):
        flight = _make_bookable_flight(legs=[_make_bookable_leg("BA", "178")])
        assert _match_flight([flight], ["BA178", "BA179"]) is None

    def test_match_when_flight_number_pre_prefixed(self):
        """Pre-prefixed flight_number ('BA178') still matches both forms.

        Guards against a double-prefix ('BABA178') if the decoder ever yields
        an already-prefixed flight number; both bare and prefixed caller forms
        must resolve.
        """
        flight = _make_bookable_flight(legs=[_make_bookable_leg("BA", "BA178")])
        assert _match_flight([flight], ["178"]) is flight
        assert _match_flight([flight], ["BA178"]) is flight


class TestSerializeDateResult:
    def _make_date_result(self, dates, price=350.0, currency="USD"):
        dr = MagicMock()
        dr.date = dates
        dr.price = price
        dr.currency = currency
        return dr

    def test_date_is_yyyy_mm_dd_string_one_way(self):
        from datetime import datetime

        from fli.models import Airport

        dr = self._make_date_result((datetime(2026, 3, 15),))
        out = _serialize_date_result(dr, [Airport.JFK], [Airport.LHR], (None, None, None))
        assert out["date"] == "2026-03-15"
        assert isinstance(out["date"], str)
        assert out["return_date"] is None

    def test_date_and_return_date_strings_round_trip(self):
        from datetime import datetime

        from fli.models import Airport

        dr = self._make_date_result((datetime(2026, 3, 15), datetime(2026, 3, 22)))
        out = _serialize_date_result(dr, [Airport.JFK], [Airport.LHR], (None, None, None))
        assert out["date"] == "2026-03-15"
        assert out["return_date"] == "2026-03-22"
        assert "booking_url" in out


class TestSerializeBookingOption:
    def _make_option(self, **overrides):
        opt = MagicMock()
        opt.vendor_name = None
        opt.vendor_code = None
        opt.fare_name = None
        opt.currency = None
        opt.booking_url = None
        opt.google_click_url = None
        opt.price = None
        opt.is_airline_direct = False
        for k, v in overrides.items():
            setattr(opt, k, v)
        return opt

    def test_populated_fields_included(self):
        opt = self._make_option(
            vendor_name="American Airlines",
            booking_url="https://aa.com/book",
            price=342.0,
            currency="USD",
            is_airline_direct=True,
        )
        result = _serialize_booking_option(opt)
        assert result["vendor_name"] == "American Airlines"
        assert result["booking_url"] == "https://aa.com/book"
        assert result["price"] == 342.0
        assert result["is_airline_direct"] is True

    def test_empty_option_serializes_to_empty_dict(self):
        result = _serialize_booking_option(self._make_option())
        assert result == {}

    def test_airline_direct_false_excluded(self):
        opt = self._make_option(vendor_name="Expedia", is_airline_direct=False)
        result = _serialize_booking_option(opt)
        assert "is_airline_direct" not in result


class TestSearchReturnsBookingUrl:
    @pytest.fixture
    def params(self):
        return FlightSearchParams(origin="JFK", destination="LHR", departure_date="2026-12-01")

    def test_booking_url_present_on_success(self, monkeypatch, params):
        flight = _make_bookable_flight()
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            lambda self, *a, **k: [flight],
        )
        result = _execute_flight_search(params)
        assert result["success"] is True
        assert "booking_url" in result
        assert "JFK" in result["booking_url"]

    def test_per_flight_booking_url_in_flights_array(self, monkeypatch, params):
        """Each flight in the flights[] array carries its own booking_url."""
        flight = _make_bookable_flight()
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            lambda self, *a, **k: [flight],
        )
        # Monkeypatch build_flight_booking_url to return a recognisable value
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.build_flight_booking_url",
            lambda self, f, **kw: "https://www.google.com/travel/flights/booking?tfs=TEST",
        )
        result = _execute_flight_search(params)
        assert result["success"] is True
        assert result["flights"][0]["booking_url"] == (
            "https://www.google.com/travel/flights/booking?tfs=TEST"
        )

    def test_top_level_search_booking_url_still_present(self, monkeypatch, params):
        """The top-level search booking_url (q= link) is kept alongside per-flight links."""
        flight = _make_bookable_flight()
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            lambda self, *a, **k: [flight],
        )
        result = _execute_flight_search(params)
        assert result["success"] is True
        # Top-level booking_url points to the search page, not a specific flight
        assert "q=" in result["booking_url"]
        # Per-flight booking_url is in each flight dict
        assert "booking_url" in result["flights"][0]

    def test_booking_url_present_when_no_flights(self, monkeypatch, params):
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            lambda self, *a, **k: None,
        )
        result = _execute_flight_search(params)
        assert result["count"] == 0
        assert "booking_url" in result


class TestExecuteBookingOptions:
    @pytest.fixture
    def params(self):
        return FlightSearchParams(origin="JFK", destination="LHR", departure_date="2026-12-01")

    def test_returns_options_with_booking_url(self, monkeypatch, params):
        flight = _make_bookable_flight()
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            lambda self, *a, **k: [flight],
        )
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.get_booking_options",
            lambda self, *a, **k: [_make_option_helper()],
        )
        result = _execute_booking_options(params, ["BA178"])
        assert result["success"] is True
        assert result["count"] == 1
        assert result["options"][0]["booking_url"] == "https://book.aa.com/x"
        assert "selected_flight" in result
        assert "booking_url" in result

    def test_selected_flight_has_per_flight_booking_url(self, monkeypatch, params):
        """selected_flight in booking-options response carries its own booking_url."""
        flight = _make_bookable_flight()
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            lambda self, *a, **k: [flight],
        )
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.get_booking_options",
            lambda self, *a, **k: [_make_option_helper()],
        )
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.build_flight_booking_url",
            lambda self, f, **kw: "https://www.google.com/travel/flights/booking?tfs=SEL",
        )
        result = _execute_booking_options(params, ["BA178"])
        assert result["success"] is True
        assert result["selected_flight"]["booking_url"] == (
            "https://www.google.com/travel/flights/booking?tfs=SEL"
        )

    def test_no_match_lists_available_flights(self, monkeypatch, params):
        flight = _make_bookable_flight()
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            lambda self, *a, **k: [flight],
        )
        result = _execute_booking_options(params, ["ZZ999"])
        assert result["success"] is False
        assert result["available_flights"] == [["BA178"]]

    def test_no_flights_returns_empty_options(self, monkeypatch, params):
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            lambda self, *a, **k: None,
        )
        result = _execute_booking_options(params, None)
        assert result["success"] is True
        assert result["options"] == []

    def test_empty_vendor_list_adds_fallback_note(self, monkeypatch, params):
        flight = _make_bookable_flight()
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            lambda self, *a, **k: [flight],
        )
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.get_booking_options",
            lambda self, *a, **k: [],
        )
        result = _execute_booking_options(params, ["BA178"])
        assert result["success"] is True
        assert result["options"] == []
        assert "booking_url" in result
        assert "note" in result
        assert "booking_url" in result["note"]
