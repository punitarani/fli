#!/usr/bin/env python3
"""Advanced date search with comprehensive validation.

This example demonstrates date search functionality with extensive validation
for round trip searches, including duration constraints and date validation.
"""

from datetime import datetime, timedelta

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
    TimeRestrictions,
    TripType,
)
from fli.search import SearchDates


def validate_dates(from_date: str, to_date: str, min_stay: int, max_stay: int):
    """Validate date ranges for round trip searches."""
    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date()
    today = datetime.now().date()

    if start <= today:
        raise ValueError("Start date must be in the future")
    if end <= start:
        raise ValueError("End date must be after start date")
    if end - start > timedelta(days=180):
        raise ValueError("Date range cannot exceed 180 days")
    if min_stay < 1:
        raise ValueError("Minimum stay must be at least 1 day")
    if max_stay > 30:
        raise ValueError("Maximum stay cannot exceed 30 days")
    if min_stay > max_stay:
        raise ValueError("Minimum stay cannot be greater than maximum stay")

    print(f"✓ Date validation passed: {from_date} to {to_date}")
    print(f"✓ Stay duration: {min_stay}-{max_stay} days")


def main():
    """Demonstrate advanced date search with validation."""
    # Create flight segments for date search
    travel_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    segments = [
        FlightSegment(
            departure_airport=[[Airport.JFK, 0]],
            arrival_airport=[[Airport.LAX, 0]],
            travel_date=travel_date,
            time_restrictions=TimeRestrictions(
                earliest_departure=9,  # 9 AM
                latest_departure=18,  # 6 PM
            ),
        )
    ]

    # Validate and create filters
    from_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
    min_stay = 2
    max_stay = 4

    try:
        validate_dates(from_date, to_date, min_stay, max_stay)
    except ValueError as e:
        print(f"❌ Validation failed: {e}")
        return

    filters = DateSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=segments,
        from_date=from_date,
        to_date=to_date,
        min_stay_days=min_stay,
        max_stay_days=max_stay,
        seat_type=SeatType.ECONOMY,
    )

    print("\n🔍 Searching for round trip dates...")
    search = SearchDates()
    results = search.search(filters)

    if not results:
        print("❌ No dates found matching criteria")
        return

    # Process results with weekend filtering
    weekend_trips = []
    for trip in results:
        travel_date = trip.date[0]  # Get the travel date from the date tuple

        # Check if travel date is on weekend (5 = Saturday, 6 = Sunday)
        if travel_date.weekday() >= 5:
            weekend_trips.append(
                {
                    "date": travel_date.strftime("%Y-%m-%d"),
                    "day": travel_date.strftime("%A"),
                    "price": trip.price,
                }
            )

    # Sort by price
    weekend_trips.sort(key=lambda x: x["price"])

    # Display results
    print(f"\n✅ Found {len(weekend_trips)} weekend flights:")
    for i, trip in enumerate(weekend_trips[:5], 1):  # Show top 5
        print(f"\n{i}. Weekend Flight:")
        print(f"   Date: {trip['date']} ({trip['day']})")
        print(f"   Price: ${trip['price']}")


if __name__ == "__main__":
    main()
