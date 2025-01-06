#!/usr/bin/env python3

import argparse
from datetime import datetime
from typing import List, Tuple

from fli.models import Airline, Airport, MaxStops, PassengerInfo, SeatType, SortBy
from fli.search import Search, SearchFilters


def parse_time_range(time_range: str) -> Tuple[int, int]:
    """Parse time range in format 'start-end' (24h format)."""
    try:
        start, end = map(int, time_range.split("-"))
        if not (0 <= start <= 23 and 0 <= end <= 23):
            raise ValueError
        return start, end
    except ValueError:
        raise ValueError("Time range must be in format 'start-end' (e.g., '6-20')")


def parse_airlines(airlines: List[str]) -> List[Airline]:
    """Parse airlines from list of airline codes."""
    return [getattr(Airline, airline.strip().upper()) for airline in airlines if airline.strip()]


def filter_flights_by_time(flights: list, start_hour: int, end_hour: int) -> list:
    """Filter flights by departure time range."""
    return [
        flight
        for flight in flights
        if any(start_hour <= leg.departure_datetime.hour <= end_hour for leg in flight.legs)
    ]


def filter_flights_by_airlines(flights: list, airlines: List[Airline]) -> list:
    """Filter flights by specified airlines."""
    return [flight for flight in flights if any(leg.airline in airlines for leg in flight.legs)]


def main():
    parser = argparse.ArgumentParser(
        description="Search for flights using simple parameters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    fli JFK LHR 2025-10-25 --time 6-20 --airlines BA KL
    fli SFO NYC 2025-11-01 --time 9-17 --stops NON_STOP --sort DURATION
    fli LAX MIA 2025-12-25 --seat BUSINESS
        """,
    )

    # Required arguments
    parser.add_argument("from_airport", help="Departure airport code (e.g., JFK)")
    parser.add_argument("to_airport", help="Arrival airport code (e.g., LON)")
    parser.add_argument("date", help="Travel date (YYYY-MM-DD)")

    # Optional arguments
    parser.add_argument("--time", help="Time range in 24h format (e.g., 6-20)")
    parser.add_argument("--airlines", nargs="+", help="List of airline codes (e.g., BA KL)")
    parser.add_argument(
        "--seat",
        choices=["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"],
        default="ECONOMY",
        help="Seat type (default: ECONOMY)",
    )
    parser.add_argument(
        "--stops",
        choices=["ANY", "NON_STOP", "ONE_STOP", "TWO_PLUS_STOPS"],
        default="ANY",
        help="Maximum number of stops (default: ANY)",
    )
    parser.add_argument(
        "--sort",
        choices=["CHEAPEST", "DURATION", "DEPARTURE_TIME", "ARRIVAL_TIME"],
        default="CHEAPEST",
        help="Sort results by (default: CHEAPEST)",
    )

    args = parser.parse_args()

    try:
        # Parse parameters
        departure_airport = getattr(Airport, args.from_airport.upper())
        arrival_airport = getattr(Airport, args.to_airport.upper())
        seat_type = getattr(SeatType, args.seat)
        stops = getattr(MaxStops, args.stops)
        sort_by = getattr(SortBy, args.sort)

        # Validate date format
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be in YYYY-MM-DD format")

        # Create search filters
        filters = SearchFilters(
            departure_airport=departure_airport,
            arrival_airport=arrival_airport,
            departure_date=args.date,
            passenger_info=PassengerInfo(adults=1),
            seat_type=seat_type,
            stops=stops,
            sort_by=sort_by,
        )

        # Perform search
        search = Search()
        flights = search.search(filters)

        if not flights:
            print("No flights found.")
            return

        # Apply time filter if specified
        if args.time:
            start_hour, end_hour = parse_time_range(args.time)
            flights = filter_flights_by_time(flights, start_hour, end_hour)

        # Apply airline filter if specified
        if args.airlines:
            airlines = parse_airlines(args.airlines)
            flights = filter_flights_by_airlines(flights, airlines)

        if not flights:
            print("No flights found matching the specified filters.")
            return

        # Display results
        for i, flight in enumerate(flights, 1):
            print(f"\nFlight Option {i}:")
            print(f"Price: ${flight.price}")
            print(f"Duration: {flight.duration} minutes")
            print(f"Stops: {flight.stops}")

            for leg in flight.legs:
                print(f"\n  Flight: {leg.airline.value} {leg.flight_number}")
                print(f"  From: {leg.departure_airport.value} at {leg.departure_datetime}")
                print(f"  To: {leg.arrival_airport.value} at {leg.arrival_datetime}")

    except (AttributeError, ValueError) as e:
        parser.error(str(e))


if __name__ == "__main__":
    main()
