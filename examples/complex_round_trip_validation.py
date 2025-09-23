#!/usr/bin/env python3
"""Complex round trip search with extensive validation.

This example demonstrates advanced round trip flight searching with
comprehensive validation, multiple passengers, and complex requirements.
"""

from datetime import datetime, timedelta

from fli.models import (
    Airline,
    Airport,
    FlightSearchFilters,
    FlightSegment,
    LayoverRestrictions,
    MaxStops,
    PassengerInfo,
    SeatType,
    TimeRestrictions,
    TripType,
)
from fli.search import SearchFlights


def validate_trip_dates(outbound_date_str: str, return_date_str: str):
    """Validate trip dates with comprehensive checks."""
    today = datetime.now().date()
    outbound_date = datetime.strptime(outbound_date_str, "%Y-%m-%d").date()
    return_date = datetime.strptime(return_date_str, "%Y-%m-%d").date()

    if outbound_date <= today:
        raise ValueError("Outbound date must be in the future")
    if return_date <= outbound_date:
        raise ValueError("Return date must be after outbound date")
    if return_date - outbound_date > timedelta(days=30):
        raise ValueError("Trip duration cannot exceed 30 days")

    print(f"✓ Dates validated: {outbound_date} to {return_date}")
    return outbound_date, return_date


def main():
    """Demonstrate complex round trip search with validation."""
    # Create flight segments with time restrictions
    outbound_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    outbound = FlightSegment(
        departure_airport=[[Airport.JFK, 0]],
        arrival_airport=[[Airport.LHR, 0]],
        travel_date=outbound_date,
        time_restrictions=TimeRestrictions(
            earliest_departure=6,  # 6 AM
            latest_departure=12,  # 12 PM
            earliest_arrival=18,  # 6 PM
            latest_arrival=23,  # 11 PM
        ),
    )

    return_date = (datetime.now() + timedelta(days=37)).strftime("%Y-%m-%d")

    return_flight = FlightSegment(
        departure_airport=[[Airport.LHR, 0]],
        arrival_airport=[[Airport.JFK, 0]],
        travel_date=return_date,
        time_restrictions=TimeRestrictions(
            earliest_departure=14,  # 2 PM
            latest_departure=20,  # 8 PM
            earliest_arrival=17,  # 5 PM
            latest_arrival=23,  # 11 PM
        ),
    )

    # Validate dates
    try:
        validate_trip_dates(outbound.travel_date, return_flight.travel_date)
    except ValueError as e:
        print(f"❌ Validation error: {e}")
        return

    # Create filters with complex requirements
    filters = FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=2, children=1, infants_on_lap=1),
        flight_segments=[outbound, return_flight],
        stops=MaxStops.ONE_STOP_OR_FEWER,
        seat_type=SeatType.BUSINESS,
        airlines=[Airline.BA, Airline.VS],  # British Airways and Virgin Atlantic
        max_duration=720,  # 12 hours max flight time
        layover_restrictions=LayoverRestrictions(
            airports=[Airport.DUB, Airport.AMS],  # Preferred layover airports
            max_duration=180,  # Maximum 3-hour layover
        ),
    )

    print("\n🔍 Searching for complex round trip flights...")
    search = SearchFlights()
    results = search.search(filters)

    if not results:
        print("❌ No flights found matching criteria")
        return

    # Process results with detailed information
    print(f"\n✅ Found {len(results)} flight combinations:")

    for i, (outbound, return_flight) in enumerate(results[:3], 1):  # Show first 3 results
        print(f"\n{'=' * 50}")
        print(f"Option {i}: Total Price: ${outbound.price + return_flight.price}")

        print("\n🛫 Outbound Flight:")
        for leg in outbound.legs:
            print(f"  Flight: {leg.airline.value} {leg.flight_number}")
            print(f"  From: {leg.departure_airport.value} at {leg.departure_datetime}")
            print(f"  To: {leg.arrival_airport.value} at {leg.arrival_datetime}")
            print(f"  Duration: {leg.duration} minutes")
            if hasattr(leg, "layover_duration") and leg.layover_duration:
                print(f"  Layover: {leg.layover_duration} minutes")

        print("\n🛬 Return Flight:")
        for leg in return_flight.legs:
            print(f"  Flight: {leg.airline.value} {leg.flight_number}")
            print(f"  From: {leg.departure_airport.value} at {leg.departure_datetime}")
            print(f"  To: {leg.arrival_airport.value} at {leg.arrival_datetime}")
            print(f"  Duration: {leg.duration} minutes")
            if hasattr(leg, "layover_duration") and leg.layover_duration:
                print(f"  Layover: {leg.layover_duration} minutes")


if __name__ == "__main__":
    main()
