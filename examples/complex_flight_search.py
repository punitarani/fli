#!/usr/bin/env python3
"""Complex flight search with multiple filters.

This example demonstrates how to search for flights with detailed filters
including airlines, duration limits, and layover restrictions.
"""

from fli.models import (
    Airline,
    Airport,
    FlightSearchFilters,
    FlightSegment,
    LayoverRestrictions,
    MaxStops,
    PassengerInfo,
    SeatType,
    TripType,
)
from fli.search import SearchFlights


def main():
    from datetime import datetime, timedelta

    # Create detailed filters
    filters = FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=2, children=1, infants_on_lap=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LHR, 0]],
                travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            )
        ],
        seat_type=SeatType.BUSINESS,
        stops=MaxStops.ONE_STOP_OR_FEWER,
        airlines=[Airline.BA, Airline.VS],  # British Airways and Virgin Atlantic
        max_duration=720,  # 12 hours in minutes
        layover_restrictions=LayoverRestrictions(
            airports=[Airport.BOS, Airport.ORD],  # Prefer these layover airports
            max_duration=180,  # Maximum 3-hour layover
        ),
    )

    search = SearchFlights()
    results = search.search(filters)

    print(f"Found {len(results)} flights:")
    for i, flight in enumerate(results, 1):
        print(f"\n--- Flight {i} ---")
        print(f"Price: ${flight.price}")
        print(f"Duration: {flight.duration} minutes")
        print(f"Stops: {flight.stops}")

        for j, leg in enumerate(flight.legs, 1):
            print(f"\nLeg {j}: {leg.airline.value} {leg.flight_number}")
            print(f"  From: {leg.departure_airport.value} at {leg.departure_datetime}")
            print(f"  To: {leg.arrival_airport.value} at {leg.arrival_datetime}")
            print(f"  Duration: {leg.duration} minutes")


if __name__ == "__main__":
    main()
