"""Tests for date search endpoints."""

from datetime import datetime, timedelta

from fastapi import status
from fastapi.testclient import TestClient

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    TripType,
)


def test_search_dates_valid(client: TestClient):
    """Test date search with valid filters."""
    valid_date_filters = DateSearchFilters(
        trip_type=TripType.ONE_WAY,
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
                travel_date=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
            )
        ],
        stops=MaxStops.ANY,
        seat_type=SeatType.ECONOMY,
        from_date=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
        to_date=(datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
    )

    response = client.post("/dates/search", json=valid_date_filters.model_dump(mode="json"))
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for date_price in data:
        assert "date" in date_price
        assert "price" in date_price
        assert isinstance(date_price["price"], float)
        assert len(date_price["date"]) == 1
        assert isinstance(date_price["date"][0], str)


def test_search_dates_round_trip(client: TestClient):
    """Test round trip date search."""
    valid_date_filters = DateSearchFilters(
        trip_type=TripType.ROUND_TRIP,
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
                travel_date=(datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"),
            ),
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.SFO, 0]],
                travel_date=(datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
            ),
        ],
        stops=MaxStops.ANY,
        seat_type=SeatType.ECONOMY,
        from_date=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
        to_date=(datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
        duration=2,
    )

    response = client.post("/dates/search", json=valid_date_filters.model_dump(mode="json"))
    assert response.status_code == status.HTTP_200_OK
    assert "X-Request-ID" in response.headers

    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for date_price in data:
        assert "date" in date_price
        assert "price" in date_price
        assert isinstance(date_price["price"], float)
        assert len(date_price["date"]) == 2
        for date in date_price["date"]:
            assert isinstance(date, str)
