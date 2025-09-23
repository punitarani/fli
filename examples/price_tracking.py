#!/usr/bin/env python3
"""Price tracking over time example.

This example demonstrates how to track flight prices over multiple days
to analyze price trends and find the best deals.
"""

import time

from fli.models import Airport, DateSearchFilters, FlightSegment, PassengerInfo
from fli.search import SearchDates


def track_prices(days=7):
    """Track flight prices over a specified number of days."""
    from datetime import datetime, timedelta

    base_date = datetime.now() + timedelta(days=30)
    travel_date = base_date.strftime("%Y-%m-%d")
    from_date = base_date.strftime("%Y-%m-%d")
    to_date = (base_date + timedelta(days=7)).strftime("%Y-%m-%d")

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

    search = SearchDates()
    price_history = {}

    for day in range(days):
        print(f"Day {day + 1}: Searching for prices...")
        results = search.search(filters)

        # Store prices
        for result in results:
            date_str = result.date[0].strftime("%Y-%m-%d")
            if date_str not in price_history:
                price_history[date_str] = []
            price_history[date_str].append(result.price)

        # Wait for next check (in a real implementation, you'd wait 24 hours)
        if day < days - 1:  # Don't wait on the last iteration
            print("Waiting for next check...")
            time.sleep(1)  # In real usage: time.sleep(86400) for 24 hours

    return price_history


def main():
    """Main function to demonstrate price tracking."""
    print("Starting price tracking demo...")
    price_history = track_prices(3)  # Track for 3 iterations as demo

    print("\n=== Price History Summary ===")
    for date, prices in price_history.items():
        min_price = min(prices)
        max_price = max(prices)
        avg_price = sum(prices) / len(prices)
        print(f"{date}: Min: ${min_price:.2f}, Max: ${max_price:.2f}, Avg: ${avg_price:.2f}")


if __name__ == "__main__":
    main()
