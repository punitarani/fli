"""Tests for the dates router endpoints."""

from datetime import datetime, timedelta

from fastapi import status
from fastapi.testclient import TestClient

from fli.models import MaxStops, SeatType


def test_search_dates_valid(client: TestClient, valid_date_filters):
    """Test valid date search."""
    response = client.post("/dates/search", json=valid_date_filters)
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]

    # Check response headers
    assert "X-Request-ID" in response.headers

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert isinstance(data, list)
        if data:  # If dates were found
            date_price = data[0]
            assert "date" in date_price
            assert "price" in date_price
            assert isinstance(date_price["price"], int | float)


def test_search_dates_invalid_filters(client: TestClient):
    """Test date search with invalid filters."""
    response = client.post(
        "/dates/search",
        json={
            "flight_segments": [],  # Empty flight segments
            "passenger_info": {"adults": 0},  # Invalid passenger count
            "stops": MaxStops.ANY.value,
            "seat_type": SeatType.ECONOMY.value,
            "from_date": datetime.now().strftime("%Y-%m-%d"),
            "to_date": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "X-Request-ID" in response.headers

    data = response.json()
    assert "detail" in data
    assert data["detail"] == "No flight segments provided"


def test_search_dates_invalid_date_range(client: TestClient, valid_date_filters):
    """Test date search with swapped date range."""
    # Modify filters to have from_date after to_date
    filters = valid_date_filters.copy()
    from_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    to_date = datetime.now().strftime("%Y-%m-%d")
    filters["from_date"] = from_date
    filters["to_date"] = to_date

    response = client.post("/dates/search", json=filters)
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]
    assert "X-Request-ID" in response.headers

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert isinstance(data, list)
        if data:  # If dates were found
            date_price = data[0]
            assert "date" in date_price
            assert "price" in date_price
            assert isinstance(date_price["price"], int | float)


def test_search_dates_past_date(client: TestClient, valid_date_filters):
    """Test date search with past date."""
    # Set to_date to yesterday
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    filters = valid_date_filters.copy()
    filters["from_date"] = tomorrow
    filters["to_date"] = yesterday

    response = client.post("/dates/search", json=filters)
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]
    assert "X-Request-ID" in response.headers

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert isinstance(data, list)
        if data:  # If dates were found
            date_price = data[0]
            assert "date" in date_price
            assert "price" in date_price
            assert isinstance(date_price["price"], int | float)


def test_search_dates_invalid_airport(client: TestClient, valid_date_filters):
    """Test date search with invalid airport."""
    # Modify filters to include invalid airport
    filters = valid_date_filters.copy()
    filters["flight_segments"][0]["departure_airport"] = [["XXX", 0]]

    response = client.post("/dates/search", json=filters)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "X-Request-ID" in response.headers
