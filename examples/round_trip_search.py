#!/usr/bin/env python3
"""Round trip flight search example.

This example demonstrates how to search for round trip flights with
outbound and return segments.
"""

from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    TripType,
)
from fli.search import SearchFlights


def main():
    # Create flight segments for round trip
    from datetime import datetime, timedelta

    outbound_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    return_date = (datetime.now() + timedelta(days=37)).strftime("%Y-%m-%d")

    flight_segments = [
        FlightSegment(
            departure_airport=[[Airport.JFK, 0]],
            arrival_airport=[[Airport.LAX, 0]],
            travel_date=outbound_date,
        ),
        FlightSegment(
            departure_airport=[[Airport.LAX, 0]],
            arrival_airport=[[Airport.JFK, 0]],
            travel_date=return_date,
        ),
    ]

    # Create filters
    filters = FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=flight_segments,
    )

    # Search flights
    search = SearchFlights()
    results = search.search(filters)

    # Process results
    for outbound, return_flight in results:
        print("\nOutbound Flight:")
        for leg in outbound.legs:
            print(f"Flight: {leg.airline.value} {leg.flight_number}")
            print(f"Departure: {leg.departure_datetime}")
            print(f"Arrival: {leg.arrival_datetime}")

        print("\nReturn Flight:")
        for leg in return_flight.legs:
            print(f"Flight: {leg.airline.value} {leg.flight_number}")
            print(f"Departure: {leg.departure_datetime}")
            print(f"Arrival: {leg.arrival_datetime}")

        print(f"\nTotal Price: ${outbound.price + return_flight.price}")


if __name__ == "__main__":
    main()
