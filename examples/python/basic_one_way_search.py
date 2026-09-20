#!/usr/bin/env python3
"""Basic one-way flight search example.

This example demonstrates how to search for one-way flights between two airports
on a specific date using the most basic configuration.
"""

from datetime import datetime, timedelta

from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.search import SearchFlights


def main():
    # Create search filters
    filters = FlightSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            )
        ],
        seat_type=SeatType.ECONOMY,
        stops=MaxStops.NON_STOP,
        sort_by=SortBy.CHEAPEST,
    )

    # Search flights
    search = SearchFlights()
    flights = search.search(filters)

    # Process results
    for flight in flights:
        print(f"💰 Price: ${flight.price}")
        print(f"⏱️ Duration: {flight.duration} minutes")
        print(f"✈️ Stops: {flight.stops}")

        for leg in flight.legs:
            print(f"\n🛫 Flight: {leg.airline.value} {leg.flight_number}")
            print(f"📍 From: {leg.departure_airport.value} at {leg.departure_datetime}")
            print(f"📍 To: {leg.arrival_airport.value} at {leg.arrival_datetime}")


if __name__ == "__main__":
    main()
