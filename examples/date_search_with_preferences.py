#!/usr/bin/env python3
"""Advanced date search with day preferences.

This example demonstrates how to search for flights across a date range
and filter results for specific days of the week (e.g., weekends only).
"""

from datetime import datetime, timedelta

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
    TripType,
)
from fli.search import SearchDates


def main():
    # Create filters for weekends only
    base_date = datetime.now() + timedelta(days=30)
    travel_date = base_date.strftime("%Y-%m-%d")
    from_date = base_date.strftime("%Y-%m-%d")
    to_date = (base_date + timedelta(days=30)).strftime("%Y-%m-%d")

    filters = DateSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=travel_date,
            )
        ],
        from_date=from_date,
        to_date=to_date,
        seat_type=SeatType.PREMIUM_ECONOMY,
    )

    search = SearchDates()
    results = search.search(filters)

    # Filter for weekends only
    weekend_results = [
        r for r in results if r.date[0].weekday() >= 5  # Saturday = 5, Sunday = 6
    ]

    print(f"Found {len(weekend_results)} weekend flights:")
    for result in weekend_results:
        day_name = result.date[0].strftime("%A")
        date_str = result.date[0].strftime("%Y-%m-%d")
        print(f"{day_name}, {date_str}: ${result.price}")


if __name__ == "__main__":
    main()
