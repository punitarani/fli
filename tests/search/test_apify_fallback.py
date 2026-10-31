"""Tests for the opt-in hosted fallback (fli/search/_apify.py). Offline."""

from datetime import datetime

import pytest

from fli.models import (
    Airline,
    Airport,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.models.google_flights.base import TripType
from fli.search import SearchFlights, _apify
from fli.search.exceptions import (
    SearchClientError,
    SearchConnectionError,
    SearchHTTPError,
    SearchParseError,
)

# Trimmed from a real run of the Actor (JFK -> LHR, 2026-12-10, captured 2026-10-31).
ITEMS = [
    {
        "best_flights": [
            {
                "flights": [
                    {
                        "departure_airport": {
                            "name": "John F. Kennedy International Airport",
                            "id": "JFK",
                            "time": "2026-12-10 08:05",
                        },
                        "arrival_airport": {
                            "name": "Heathrow Airport",
                            "id": "LHR",
                            "time": "2026-12-10 20:00",
                        },
                        "duration": 415,
                        "airplane": "Boeing 777",
                        "airline": "British Airways",
                        "travel_class": "Economy",
                        "flight_number": "BA 178",
                        "legroom": "31 in",
                    }
                ],
                "total_duration": 415,
                "carbon_emissions": {
                    "this_flight": 442000,
                    "typical_for_this_route": 434000,
                    "difference_percent": 2,
                },
                "price": 300,
                "type": "One way",
            }
        ],
        "other_flights": [
            {
                "flights": [
                    {
                        "departure_airport": {
                            "name": "John F. Kennedy International Airport",
                            "id": "JFK",
                            "time": "2026-12-10 17:00",
                        },
                        "arrival_airport": {
                            "name": "Dublin Airport",
                            "id": "DUB",
                            "time": "2026-12-11 04:30",
                        },
                        "duration": 390,
                        "airplane": "Airbus A330",
                        "airline": "Aer Lingus",
                        "flight_number": "EI 104",
                        "legroom": "31 in",
                        "overnight": True,
                    },
                    {
                        "departure_airport": {
                            "name": "Dublin Airport",
                            "id": "DUB",
                            "time": "2026-12-11 06:35",
                        },
                        "arrival_airport": {
                            "name": "Heathrow Airport",
                            "id": "LHR",
                            "time": "2026-12-11 08:05",
                        },
                        "duration": 90,
                        "airplane": "Airbus A320neo",
                        "airline": "Aer Lingus",
                        "flight_number": "EI 152",
                        "legroom": "29 in",
                    },
                ],
                "layovers": [{"duration": 125, "name": "Dublin Airport", "id": "DUB"}],
                "total_duration": 605,
                "carbon_emissions": {"this_flight": 392000},
                "price": 298,
                "type": "One way",
            },
            {
                # An airport fli has never heard of: skipped, not fatal.
                "flights": [
                    {
                        "departure_airport": {"id": "JFK", "time": "2026-12-10 09:00"},
                        "arrival_airport": {"id": "QQQ", "time": "2026-12-10 21:00"},
                        "duration": 420,
                        "flight_number": "BA 999",
                    }
                ],
                "total_duration": 420,
                "price": 250,
            },
        ],
    }
]


def _filters(**overrides) -> FlightSearchFilters:
    fields = {
        "passenger_info": PassengerInfo(adults=2, infants_on_lap=1),
        "flight_segments": [
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LHR, 0]],
                travel_date="2026-12-10",
            )
        ],
        "stops": MaxStops.ONE_STOP_OR_FEWER,
        "sort_by": SortBy.CHEAPEST,
    }
    fields.update(overrides)
    return FlightSearchFilters(**fields)


@pytest.fixture(autouse=True)
def _clock(pin_today):
    pin_today("2026-10-31")


@pytest.fixture
def blocked(monkeypatch):
    """Make every direct search fail with Google's HTTP 429."""

    def _raise(self, *args, **kwargs):
        raise SearchHTTPError("Google Flights returned an error (HTTP 429).", status_code=429)

    monkeypatch.setattr(SearchFlights, "_fetch_flights", _raise)


@pytest.fixture
def hosted(monkeypatch):
    """Stub the Apify call; return the list of request bodies it received."""
    calls: list[dict] = []

    def _post(url, token, body):
        calls.append({"url": url, "token": token, "body": body})
        return ITEMS

    monkeypatch.setattr(_apify, "_post_json", _post)
    return calls


def test_no_token_raises_the_original_error(monkeypatch, blocked, hosted):
    monkeypatch.delenv(_apify.TOKEN_ENV_VAR, raising=False)
    with pytest.raises(SearchHTTPError):
        SearchFlights().search(_filters())
    assert hosted == []


def test_blocked_one_way_search_falls_back(monkeypatch, blocked, hosted):
    monkeypatch.setenv(_apify.TOKEN_ENV_VAR, "apify_api_test")
    flights = SearchFlights().search(_filters(), currency="usd")

    assert [f.price for f in flights] == [298, 300]  # sorted cheapest first, QQQ row dropped
    connecting, nonstop = flights
    assert nonstop.legs[0].airline == Airline.BA
    assert nonstop.legs[0].flight_number == "178"
    assert nonstop.legs[0].departure_datetime == datetime(2026, 12, 10, 8, 5)
    assert nonstop.co2_emissions_delta_pct == 2
    assert connecting.stops == 1
    assert connecting.duration == 605
    assert connecting.layovers[0].airport == Airport.DUB
    assert connecting.layovers[0].duration == 125
    assert connecting.legs[0].overnight is True
    assert connecting.currency == "USD"

    (call,) = hosted
    assert call["token"] == "apify_api_test"
    assert call["body"]["departure_id"] == "JFK"
    assert call["body"]["arrival_id"] == "LHR"
    assert call["body"]["adults"] == 2
    assert call["body"]["infants"] == 1
    assert call["body"]["max_stops"] == 1


def test_client_side_filters_still_apply(monkeypatch, blocked, hosted):
    monkeypatch.setenv(_apify.TOKEN_ENV_VAR, "apify_api_test")
    flights = SearchFlights().search(_filters(airlines=[Airline.BA]))
    assert [f.legs[0].airline for f in flights] == [Airline.BA]


@pytest.mark.parametrize(
    "overrides",
    [
        {"seat_type": SeatType.BUSINESS},
        {
            "trip_type": TripType.ROUND_TRIP,
            "flight_segments": [
                FlightSegment(
                    departure_airport=[[Airport.JFK, 0]],
                    arrival_airport=[[Airport.LHR, 0]],
                    travel_date="2026-12-10",
                ),
                FlightSegment(
                    departure_airport=[[Airport.LHR, 0]],
                    arrival_airport=[[Airport.JFK, 0]],
                    travel_date="2026-12-17",
                ),
            ],
        },
    ],
)
def test_searches_the_actor_cannot_answer_do_not_fall_back(monkeypatch, blocked, hosted, overrides):
    monkeypatch.setenv(_apify.TOKEN_ENV_VAR, "apify_api_test")
    with pytest.raises(SearchHTTPError):
        SearchFlights().search(_filters(**overrides))
    assert hosted == []


def test_a_failed_fallback_raises_the_original_error(monkeypatch, blocked):
    monkeypatch.setenv(_apify.TOKEN_ENV_VAR, "apify_api_test")

    def _fail(url, token, body):
        raise ValueError("not JSON")

    monkeypatch.setattr(_apify, "_post_json", _fail)
    with pytest.raises(SearchHTTPError):
        SearchFlights().search(_filters())


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (SearchHTTPError("x", status_code=429), True),
        (SearchHTTPError("x", status_code=403), True),
        (SearchHTTPError("x", status_code=400), False),
        (SearchParseError("no ds:1"), True),
        (SearchConnectionError("dns"), False),
        (SearchClientError("other"), False),
    ],
)
def test_only_refusals_count_as_blocked(exc, expected):
    assert _apify.is_blocked(exc) is expected


def test_locale_maps_to_the_actor_enums():
    body = _apify.actor_input(_filters(), currency="eur", language="en-IN", country="GB")
    assert (body["currency"], body["hl"], body["gl"]) == ("EUR", "en", "uk")
    body = _apify.actor_input(_filters(stops=MaxStops.ANY), country="ZZ")
    assert "gl" not in body and "max_stops" not in body
