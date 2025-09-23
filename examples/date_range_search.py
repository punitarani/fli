#!/usr/bin/env python3
"""Date range search example.

This example demonstrates how to search for the cheapest flights
across a range of dates.
"""

from fli.models import Airport, DateSearchFilters, FlightSegment, PassengerInfo
from fli.search import SearchDates


def main():
    from datetime import datetime, timedelta

    # Create future dates
    base_date = datetime.now() + timedelta(days=30)
    travel_date = base_date.strftime("%Y-%m-%d")
    from_date = base_date.strftime("%Y-%m-%d")
    to_date = (base_date + timedelta(days=30)).strftime("%Y-%m-%d")

    # Create filters
    filters = DateSearchFilters(
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
    )

    # Search dates
    search = SearchDates()
    results = search.search(filters)

    # Process results
    for date_price in results:
        print(f"Date: {date_price.date}, Price: ${date_price.price}")


if __name__ == "__main__":
    main()
