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


def validate_dates(from_date: str, to_date: str, min_stay: int, max_stay: int) -> None:
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


def main() -> None:
    """Demonstrate advanced date search with validation."""
    from_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
    min_stay = 2
    max_stay = 4

    try:
        validate_dates(from_date, to_date, min_stay, max_stay)
    except ValueError as exc:
        print(f"❌ Validation failed: {exc}")
        return

    stay_lengths = range(min_stay, max_stay + 1)
    search = SearchDates()
    weekend_trips: list[dict[str, str | int | float]] = []

    print("\n🔍 Searching for round trip dates...")
    for duration in stay_lengths:
        outbound_date = from_date
        return_date = (
            datetime.strptime(outbound_date, "%Y-%m-%d") + timedelta(days=duration)
        ).strftime("%Y-%m-%d")

        flight_segments = [
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=outbound_date,
                time_restrictions=TimeRestrictions(
                    earliest_departure=9,  # 9 AM
                    latest_departure=18,  # 6 PM
                ),
            ),
            FlightSegment(
                departure_airport=[[Airport.LAX, 0]],
                arrival_airport=[[Airport.JFK, 0]],
                travel_date=return_date,
            ),
        ]

        filters = DateSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=flight_segments,
            from_date=from_date,
            to_date=to_date,
            duration=duration,
            seat_type=SeatType.ECONOMY,
        )

        results = search.search(filters)
        if not results:
            continue

        for trip in results:
            outbound, inbound = trip.date
            if outbound.weekday() >= 5:  # Saturday = 5, Sunday = 6
                weekend_trips.append(
                    {
                        "outbound": outbound.strftime("%Y-%m-%d"),
                        "return": inbound.strftime("%Y-%m-%d"),
                        "stay_length": duration,
                        "price": trip.price,
                    }
                )

    if not weekend_trips:
        print("❌ No weekend trips found in the specified range")
        return

    weekend_trips.sort(key=lambda trip: trip["price"])

    print(f"\n✅ Found {len(weekend_trips)} weekend flight combinations:")
    for index, trip in enumerate(weekend_trips[:5], 1):  # Show top 5 options
        print(f"\n{index}. Weekend Trip:")
        print(f"   Outbound: {trip['outbound']}")
        print(f"   Return:   {trip['return']}")
        print(f"   Stay:     {trip['stay_length']} days")
        print(f"   Price:    ${trip['price']}")


if __name__ == "__main__":
    main()
