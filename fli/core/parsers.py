"""Shared parsing utilities for flight search parameters.

This module provides parsing functions used by both the CLI and MCP interfaces
to convert user input into domain model objects.
"""

from enum import Enum
from typing import TypeVar

from fli.models import Airline, Airport, MaxStops, SeatType, SortBy

T = TypeVar("T", bound=Enum)


class ParseError(ValueError):
    """Error raised when parsing fails."""

    pass


def resolve_enum(enum_cls: type[T], name: str) -> T:
    """Resolve an enum member by name with normalized errors.

    Args:
        enum_cls: The enum class to resolve from
        name: The name of the enum member (case-insensitive)

    Returns:
        The resolved enum member

    Raises:
        ParseError: If the name is not a valid enum member

    """
    try:
        return getattr(enum_cls, name.upper())
    except AttributeError as e:
        valid_values = [m.name for m in enum_cls]
        raise ParseError(
            f"Invalid {enum_cls.__name__} value: '{name}'. Valid values: {', '.join(valid_values)}"
        ) from e


def resolve_airport(code: str) -> Airport:
    """Resolve an airport code to an Airport enum.

    Args:
        code: IATA airport code (e.g., 'JFK', 'LHR')

    Returns:
        The corresponding Airport enum member

    Raises:
        ParseError: If the code is not a valid airport

    """
    try:
        return getattr(Airport, code.upper())
    except AttributeError as e:
        raise ParseError(f"Invalid airport code: '{code}'") from e


def parse_airlines(codes: list[str] | None) -> list[Airline] | None:
    """Parse a list of airline codes into Airline enums.

    Args:
        codes: List of IATA airline codes (e.g., ['BA', 'KL'])

    Returns:
        List of Airline enums, or None if input is empty

    Raises:
        ParseError: If any code is not a valid airline

    """
    if not codes:
        return None

    airlines = []
    for code in codes:
        code = code.strip().upper()
        if not code:
            continue
        try:
            airline = getattr(Airline, code)
            airlines.append(airline)
        except AttributeError as e:
            raise ParseError(f"Invalid airline code: '{code}'") from e

    return airlines if airlines else None


def parse_max_stops(stops: str) -> MaxStops:
    """Parse a stops parameter into a MaxStops enum.

    Accepts both string names (ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS)
    and integer values (0, 1, 2+).

    Args:
        stops: Stops value as string or integer representation

    Returns:
        The corresponding MaxStops enum member

    Raises:
        ParseError: If the value is not valid

    """
    # Mapping for user-friendly names
    stops_map = {
        "ANY": MaxStops.ANY,
        "NON_STOP": MaxStops.NON_STOP,
        "NONSTOP": MaxStops.NON_STOP,
        "ONE_STOP": MaxStops.ONE_STOP_OR_FEWER,
        "ONE_STOP_OR_FEWER": MaxStops.ONE_STOP_OR_FEWER,
        "TWO_PLUS_STOPS": MaxStops.TWO_OR_FEWER_STOPS,
        "TWO_OR_FEWER_STOPS": MaxStops.TWO_OR_FEWER_STOPS,
    }

    # Try as integer first
    try:
        stops_int = int(stops)
        if stops_int == 0:
            return MaxStops.NON_STOP
        elif stops_int == 1:
            return MaxStops.ONE_STOP_OR_FEWER
        elif stops_int >= 2:
            return MaxStops.TWO_OR_FEWER_STOPS
        else:
            return MaxStops.ANY
    except ValueError:
        pass

    # Try as string name
    upper_stops = stops.upper()
    if upper_stops in stops_map:
        return stops_map[upper_stops]

    raise ParseError(
        f"Invalid max_stops value: '{stops}'. "
        f"Valid values: ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS, or 0/1/2"
    )


def parse_cabin_class(cabin_class: str) -> SeatType:
    """Parse a cabin class string into a SeatType enum.

    Args:
        cabin_class: Cabin class name (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)

    Returns:
        The corresponding SeatType enum member

    Raises:
        ParseError: If the value is not valid

    """
    try:
        return getattr(SeatType, cabin_class.upper())
    except AttributeError as e:
        valid_values = [m.name for m in SeatType]
        raise ParseError(
            f"Invalid cabin_class value: '{cabin_class}'. Valid values: {', '.join(valid_values)}"
        ) from e


def parse_sort_by(sort_by: str) -> SortBy:
    """Parse a sort_by string into a SortBy enum.

    Args:
        sort_by: Sort option (CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME)

    Returns:
        The corresponding SortBy enum member

    Raises:
        ParseError: If the value is not valid

    """
    try:
        return getattr(SortBy, sort_by.upper())
    except AttributeError as e:
        valid_values = [m.name for m in SortBy]
        raise ParseError(
            f"Invalid sort_by value: '{sort_by}'. Valid values: {', '.join(valid_values)}"
        ) from e


def parse_time_range(time_range: str) -> tuple[int, int]:
    """Parse a time range string into start and end hours.

    Args:
        time_range: Time range in 'HH-HH' format (e.g., '6-20')

    Returns:
        Tuple of (start_hour, end_hour)

    Raises:
        ParseError: If the format is invalid

    """
    try:
        parts = time_range.split("-")
        if len(parts) != 2:
            raise ValueError("Invalid format")

        start_hour = int(parts[0].strip())
        end_hour = int(parts[1].strip())

        if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
            raise ValueError("Hours must be between 0 and 23")

        return start_hour, end_hour
    except (ValueError, AttributeError) as e:
        raise ParseError(
            f"Invalid time range format: '{time_range}'. Expected 'HH-HH' (e.g., '6-20')"
        ) from e
