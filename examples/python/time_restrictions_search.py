#!/usr/bin/env python3
"""Flight search with time restrictions.

This example demonstrates how to search for flights with specific
departure and arrival time preferences.
"""

from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    TimeRestrictions,
    TripType,
)
from fli.search import SearchFlights


def main():
    from datetime import datetime, timedelta

    # Create filters with time restrictions
    filters = FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                time_restrictions=TimeRestrictions(
                    earliest_departure=6,  # 6 AM
                    latest_departure=10,  # 10 AM
                    earliest_arrival=12,  # 12 PM
                    latest_arrival=18,  # 6 PM
                ),
            )
        ],
    )

    search = SearchFlights()
    results = search.search(filters)

    print(f"Found {len(results)} flights with time restrictions:")
    for i, flight in enumerate(results, 1):
        print(f"\n--- Flight {i} ---")
        print(f"Price: ${flight.price}")
        print(f"Duration: {flight.duration} minutes")

        for leg in flight.legs:
            departure_time = leg.departure_datetime.strftime("%H:%M")
            arrival_time = leg.arrival_datetime.strftime("%H:%M")
            print(f"Flight: {leg.airline.value} {leg.flight_number}")
            print(f"  Departure: {departure_time} from {leg.departure_airport.value}")
            print(f"  Arrival: {arrival_time} at {leg.arrival_airport.value}")


if __name__ == "__main__":
    main()
