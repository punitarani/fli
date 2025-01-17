"""Tests for the flights router endpoints."""

from datetime import datetime, timedelta

from fastapi import status
from fastapi.testclient import TestClient

from fli.models import MaxStops, SeatType


def test_search_flights_valid(client: TestClient, valid_search_filters):
    """Test valid flight search."""
    response = client.post("/flights/search", json=valid_search_filters)
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]

    # Check response headers
    assert "X-Request-ID" in response.headers

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert isinstance(data, list)
        if data:  # If flights were found
            flight = data[0]
            assert "price" in flight
            assert isinstance(flight["price"], int | float)
            assert "legs" in flight
            assert isinstance(flight["legs"], list)


def test_search_flights_invalid_filters(client: TestClient):
    """Test flight search with invalid filters."""
    response = client.post(
        "/flights/search",
        json={
            "flight_segments": [],  # Empty flight segments
            "passenger_info": {"adults": 0},  # Invalid passenger count
            "stops": MaxStops.ANY.value,
            "seat_type": SeatType.ECONOMY.value,
            "travel_date": datetime.now().strftime("%Y-%m-%d"),
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "X-Request-ID" in response.headers

    data = response.json()
    assert "detail" in data
    assert data["detail"] == "No flight segments provided"


def test_search_flights_invalid_airport(client: TestClient, valid_search_filters):
    """Test flight search with invalid airport."""
    # Modify filters to include invalid airport
    filters = valid_search_filters.copy()
    filters["flight_segments"][0]["departure_airport"] = [["XXX", 0]]

    response = client.post("/flights/search", json=filters)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "X-Request-ID" in response.headers


def test_search_flights_invalid_passenger_info(client: TestClient, valid_search_filters):
    """Test flight search with invalid passenger info."""
    # Remove passenger info
    filters = valid_search_filters.copy()
    del filters["passenger_info"]

    response = client.post("/flights/search", json=filters)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "X-Request-ID" in response.headers

    data = response.json()
    assert "detail" in data
    assert "invalid passenger" in data["detail"].lower()


def test_search_flights_invalid_date(client: TestClient, valid_search_filters):
    """Test flight search with past date."""
    # Set travel date to yesterday
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    filters = valid_search_filters.copy()
    filters["flight_segments"][0]["travel_date"] = yesterday

    response = client.post("/flights/search", json=filters)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "X-Request-ID" in response.headers

    data = response.json()
    assert "detail" in data
    assert "past" in data["detail"].lower()
