"""Tests for flight search endpoints."""

from datetime import datetime, timedelta

from fastapi import status
from fastapi.testclient import TestClient

from fli.models import (
    Airport,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
    TripType,
)


def test_search_flights_valid(client: TestClient):
    """Test flight search with valid filters."""
    valid_search_filters = FlightSearchFilters(
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
        sort_by=SortBy.NONE,
    )

    response = client.post("/flights/search", json=valid_search_filters.model_dump(mode="json"))
    assert response.status_code == status.HTTP_200_OK
    assert "X-Request-ID" in response.headers

    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for flight in data:
        assert "price" in flight
        assert "duration" in flight
        assert "stops" in flight
        assert "legs" in flight
        assert isinstance(flight["legs"], list)
        assert len(flight["legs"]) > 0
        for leg in flight["legs"]:
            assert "airline" in leg
            assert "flight_number" in leg
            assert "departure_airport" in leg
            assert "arrival_airport" in leg
            assert "departure_datetime" in leg
            assert "arrival_datetime" in leg
            assert "duration" in leg


def test_search_flights_round_trip(client: TestClient):
    """Test round trip flight search."""
    valid_search_filters = FlightSearchFilters(
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
                travel_date=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
            ),
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.SFO, 0]],
                travel_date=(datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
            ),
        ],
        stops=MaxStops.ANY,
        seat_type=SeatType.ECONOMY,
        sort_by=SortBy.NONE,
    )

    response = client.post("/flights/search", json=valid_search_filters.model_dump(mode="json"))
    assert response.status_code == status.HTTP_200_OK
    assert "X-Request-ID" in response.headers

    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for flight in data:
        assert isinstance(flight, list)
        assert len(flight) == 2
        for flight_result in flight:
            flight_result = FlightResult.model_validate(flight_result)
            for leg in flight_result.legs:
                leg = FlightLeg.model_validate(leg)
