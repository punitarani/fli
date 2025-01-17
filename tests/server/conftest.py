"""Test configuration and fixtures."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fli.models import Airport, MaxStops, SeatType
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
def valid_search_filters() -> dict:
    """Create valid flight search filters for testing."""
    return {
        "passenger_info": {
            "adults": 1,
            "children": 0,
            "infants_in_seat": 0,
            "infants_in_lap": 0,
        },
        "flight_segments": [
            {
                "departure_airport": [[Airport.SFO.value, 0]],
                "arrival_airport": [[Airport.JFK.value, 0]],
                "travel_date": tomorrow.strftime("%Y-%m-%d"),
            }
        ],
        "stops": MaxStops.ANY.value,
        "seat_type": SeatType.ECONOMY.value,
    }


@pytest.fixture
def valid_date_filters() -> dict:
    """Create valid date search filters for testing."""
    return {
        "passenger_info": {
            "adults": 1,
            "children": 0,
            "infants_in_seat": 0,
            "infants_in_lap": 0,
        },
        "flight_segments": [
            {
                "departure_airport": [[Airport.SFO.value, 0]],
                "arrival_airport": [[Airport.JFK.value, 0]],
                "travel_date": tomorrow.strftime("%Y-%m-%d"),
            }
        ],
        "from_date": tomorrow.strftime("%Y-%m-%d"),
        "to_date": next_week.strftime("%Y-%m-%d"),
        "stops": MaxStops.ANY.value,
        "seat_type": SeatType.ECONOMY.value,
    }
