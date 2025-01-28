"""Test configuration and fixtures."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
)
from fli.server.main import app

# Common test data
tomorrow = datetime.now() + timedelta(days=1)
next_week = datetime.now() + timedelta(days=7)
yesterday = datetime.now() - timedelta(days=1)


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def valid_search_filters() -> FlightSearchFilters:
    """Create valid flight search filters for testing."""
    return FlightSearchFilters(
        passenger_info=PassengerInfo(
            adults=1,
            children=0,
            infants_in_seat=0,
            infants_on_lap=0,
        ),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.SFO, 0]],
                arrival_airport=[[Airport.JFK, 0]],
                travel_date=tomorrow.strftime("%Y-%m-%d"),
            )
        ],
        stops=MaxStops.ANY,
        seat_type=SeatType.ECONOMY,
    )


@pytest.fixture
def valid_date_filters() -> DateSearchFilters:
    """Create valid date search filters for testing."""
    return DateSearchFilters(
        passenger_info=PassengerInfo(
            adults=1,
            children=0,
            infants_in_seat=0,
            infants_on_lap=0,
        ),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.SFO, 0]],
                arrival_airport=[[Airport.JFK, 0]],
                travel_date=tomorrow.strftime("%Y-%m-%d"),
            )
        ],
        from_date=tomorrow.strftime("%Y-%m-%d"),
        to_date=next_week.strftime("%Y-%m-%d"),
        stops=MaxStops.ANY,
        seat_type=SeatType.ECONOMY,
    )
