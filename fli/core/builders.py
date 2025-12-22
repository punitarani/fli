"""Shared building utilities for constructing search filters.

This module provides builder functions used by both the CLI and MCP interfaces
to construct flight search filter objects.
"""

from datetime import datetime, timedelta

from fli.models import Airport, FlightSegment, TimeRestrictions, TripType


def build_time_restrictions(
    departure_window: str | None = None,
    arrival_window: str | None = None,
) -> TimeRestrictions | None:
    """Build a TimeRestrictions object from time window strings.

    Args:
        departure_window: Departure time range in 'HH-HH' format (e.g., '6-20')
        arrival_window: Arrival time range in 'HH-HH' format (e.g., '8-22')

    Returns:
        TimeRestrictions object, or None if no restrictions specified

    """
    if not departure_window and not arrival_window:
        return None

    earliest_departure = None
    latest_departure = None
    earliest_arrival = None
    latest_arrival = None

    if departure_window:
        from fli.core.parsers import parse_time_range

        earliest_departure, latest_departure = parse_time_range(departure_window)

    if arrival_window:
        from fli.core.parsers import parse_time_range

        earliest_arrival, latest_arrival = parse_time_range(arrival_window)

    return TimeRestrictions(
        earliest_departure=earliest_departure,
        latest_departure=latest_departure,
        earliest_arrival=earliest_arrival,
        latest_arrival=latest_arrival,
    )


def build_flight_segments(
    origin: Airport,
    destination: Airport,
    departure_date: str,
    return_date: str | None = None,
    time_restrictions: TimeRestrictions | None = None,
) -> tuple[list[FlightSegment], TripType]:
    """Build flight segments for a search request.

    Args:
        origin: Departure airport
        destination: Arrival airport
        departure_date: Outbound travel date in YYYY-MM-DD format
        return_date: Return travel date in YYYY-MM-DD format (optional)
        time_restrictions: Time restrictions to apply to segments

    Returns:
        Tuple of (list of FlightSegment objects, TripType)

    """
    segments = [
        FlightSegment(
            departure_airport=[[origin, 0]],
            arrival_airport=[[destination, 0]],
            travel_date=departure_date,
            time_restrictions=time_restrictions,
        )
    ]

    trip_type = TripType.ONE_WAY

    if return_date:
        trip_type = TripType.ROUND_TRIP
        segments.append(
            FlightSegment(
                departure_airport=[[destination, 0]],
                arrival_airport=[[origin, 0]],
                travel_date=return_date,
                time_restrictions=time_restrictions,
            )
        )

    return segments, trip_type


def build_date_search_segments(
    origin: Airport,
    destination: Airport,
    start_date: str,
    trip_duration: int | None = None,
    is_round_trip: bool = False,
    time_restrictions: TimeRestrictions | None = None,
) -> tuple[list[FlightSegment], TripType]:
    """Build flight segments for a date range search.

    Args:
        origin: Departure airport
        destination: Arrival airport
        start_date: Start date of the search range in YYYY-MM-DD format
        trip_duration: Duration of the trip in days (for round trips)
        is_round_trip: Whether to search for round-trip flights
        time_restrictions: Time restrictions to apply to segments

    Returns:
        Tuple of (list of FlightSegment objects, TripType)

    """
    segments = [
        FlightSegment(
            departure_airport=[[origin, 0]],
            arrival_airport=[[destination, 0]],
            travel_date=start_date,
            time_restrictions=time_restrictions,
        )
    ]

    trip_type = TripType.ONE_WAY

    if is_round_trip:
        trip_type = TripType.ROUND_TRIP
        return_date = (
            datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=trip_duration or 3)
        ).strftime("%Y-%m-%d")

        segments.append(
            FlightSegment(
                departure_airport=[[destination, 0]],
                arrival_airport=[[origin, 0]],
                travel_date=return_date,
                time_restrictions=time_restrictions,
            )
        )

    return segments, trip_type
