#!/usr/bin/env python3
"""Multi-city flight search example.

This example demonstrates how to search a multi-city itinerary (three or
more one-way legs on different dates) in a single request. Multi-city
results come back as tuples of ``FlightResult`` — one entry per leg, in
the order the legs were supplied.
"""

from datetime import datetime, timedelta

from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
    TripType,
)
from fli.search import SearchFlights


def main():
    base = datetime.now() + timedelta(days=30)

    def leg(origin: Airport, destination: Airport, day_offset: int) -> FlightSegment:
        return FlightSegment(
            departure_airport=[[origin, 0]],
            arrival_airport=[[destination, 0]],
            travel_date=(base + timedelta(days=day_offset)).strftime("%Y-%m-%d"),
        )

    # JFK -> LHR, a few days in London, LHR -> CDG, then CDG -> JFK home.
    filters = FlightSearchFilters(
        trip_type=TripType.MULTI_CITY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            leg(Airport.JFK, Airport.LHR, 0),
            leg(Airport.LHR, Airport.CDG, 4),
            leg(Airport.CDG, Airport.JFK, 7),
        ],
        seat_type=SeatType.ECONOMY,
    )

    search = SearchFlights()
    # top_n controls how many outbound options each leg is expanded against.
    itineraries = search.search(filters, top_n=3)

    if not itineraries:
        print("No itineraries found.")
        return

    print(f"Found {len(itineraries)} multi-city itineraries:\n")
    for i, legs in enumerate(itineraries, 1):
        total = sum(segment.price for segment in legs)
        print(f"--- Itinerary {i} — total ${total:.0f} ---")
        for segment in legs:
            first, last = segment.legs[0], segment.legs[-1]
            print(
                f"  {first.departure_airport.value} -> {last.arrival_airport.value}"
                f"  ${segment.price:.0f}  {segment.duration} min  {segment.stops} stop(s)"
            )
        print()


if __name__ == "__main__":
    main()
