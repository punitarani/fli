from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from fli.models import (
    Airline,
    Airport,
    FlightLeg,
    FlightResult,
)


@pytest.fixture
def mock_search_flights(monkeypatch):
    """Mock the SearchFlights class."""
    mock = MagicMock()
    mock.search.return_value = [
        FlightResult(
            price=299.99,
            duration=180,
            stops=0,
            legs=[
                FlightLeg(
                    airline=Airline.DL,
                    flight_number="DL123",
                    departure_airport=Airport.JFK,
                    arrival_airport=Airport.LAX,
                    departure_datetime=datetime.now(),
                    arrival_datetime=datetime.now() + timedelta(hours=3),
                    duration=180,
                )
            ],
        ),
        FlightResult(
            price=399.99,
            duration=240,
            stops=1,
            legs=[
                FlightLeg(
                    airline=Airline.UA,
                    flight_number="UA456",
                    departure_airport=Airport.JFK,
                    arrival_airport=Airport.ORD,
                    departure_datetime=datetime.now(),
                    arrival_datetime=datetime.now() + timedelta(hours=2),
                    duration=120,
                ),
                FlightLeg(
                    airline=Airline.UA,
                    flight_number="UA789",
                    departure_airport=Airport.ORD,
                    arrival_airport=Airport.LAX,
                    departure_datetime=datetime.now() + timedelta(hours=3),
                    arrival_datetime=datetime.now() + timedelta(hours=4),
                    duration=120,
                ),
            ],
        ),
    ]

    # Add round-trip mock results
    mock.search_round_trip.return_value = [
        {
            "outbound": FlightResult(
                price=299.99,
                duration=180,
                stops=0,
                legs=[
                    FlightLeg(
                        airline=Airline.DL,
                        flight_number="DL123",
                        departure_airport=Airport.JFK,
                        arrival_airport=Airport.LAX,
                        departure_datetime=datetime.now(),
                        arrival_datetime=datetime.now() + timedelta(hours=3),
                        duration=180,
                    )
                ],
            ),
            "return": FlightResult(
                price=299.99,
                duration=180,
                stops=0,
                legs=[
                    FlightLeg(
                        airline=Airline.DL,
                        flight_number="DL456",
                        departure_airport=Airport.LAX,
                        arrival_airport=Airport.JFK,
                        departure_datetime=datetime.now() + timedelta(days=7),
                        arrival_datetime=datetime.now() + timedelta(days=7, hours=3),
                        duration=180,
                    )
                ],
            ),
            "total_price": 599.98,
        }
    ]
    monkeypatch.setattr("fli.search.flights.SearchFlights.__new__", lambda cls: mock)
    monkeypatch.setattr("fli.search.SearchFlights.__new__", lambda cls: mock)
    return mock


@pytest.fixture
def mock_search_dates(monkeypatch):
    """Mock SearchDates class."""
    mock = MagicMock()
    monkeypatch.setattr("fli.search.dates.SearchDates.__new__", lambda cls: mock)
    monkeypatch.setattr("fli.search.SearchDates.__new__", lambda cls: mock)
    return mock


@pytest.fixture
def mock_console(monkeypatch):
    """Mock the rich console to prevent output during tests."""
    mock = MagicMock()
    monkeypatch.setattr("fli.cli.utils.console", mock)
    return mock
