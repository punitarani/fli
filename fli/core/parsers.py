"""Shared parsing utilities for flight search parameters.

This module provides parsing functions used by both the CLI and MCP interfaces
to convert user input into domain model objects.
"""

import re
from enum import Enum
from typing import TypeVar

from fli.models import (
    Airline,
    Airport,
    Alliance,
    Currency,
    EmissionsFilter,
    MaxStops,
    SeatType,
    SortBy,
)

_AIRLINE_SEPARATORS = re.compile(r"[,\s]+")

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

    Each item may itself contain multiple codes separated by commas or whitespace,
    so callers can pass either ``["BA", "KL"]`` (one code per item) or
    ``["BA,KL"]`` / ``["BA KL"]`` (combined). This lets the CLI accept the
    documented ``--airlines BA,KL`` and ``--airlines "BA KL"`` forms in addition
    to the repeated-flag form Typer collects natively.

    Args:
        codes: List of IATA airline codes; entries may be combined with commas or
            whitespace (e.g., ['BA', 'KL'] or ['BA,KL'] or ['BA KL']).

    Returns:
        List of Airline enums, or None if ``codes`` is None or an empty list.

    Raises:
        ParseError: If any code is not a valid airline, or if ``codes`` was
            non-empty but contained no parsable codes (e.g., [","]).

    """
    if not codes:
        return None

    expanded = [
        token.strip().upper()
        for item in codes
        for token in _AIRLINE_SEPARATORS.split(item)
        if token.strip()
    ]
    if not expanded:
        raise ParseError(f"No valid airline codes found in: {codes!r}")

    airlines = []
    for code in expanded:
        # Airline codes starting with a digit need an underscore prefix
        # to match the Airline enum member names (e.g., "3F" -> "_3F")
        enum_key = f"_{code}" if code[0].isdigit() else code
        try:
            airline = getattr(Airline, enum_key)
            airlines.append(airline)
        except AttributeError as e:
            raise ParseError(f"Invalid airline code: '{code}'") from e

    return airlines


def parse_alliances(codes: list[str] | None) -> list[Alliance] | None:
    """Parse a list of alliance identifiers into :class:`Alliance` enums.

    Each item may itself contain multiple comma- or whitespace-separated
    values, so the CLI can accept ``--alliance ONEWORLD,SKYTEAM`` and
    repeated ``--alliance ONEWORLD --alliance STAR_ALLIANCE`` equally.
    Case-insensitive; ``"Star Alliance"`` and ``"star_alliance"`` both
    resolve to :data:`Alliance.STAR_ALLIANCE`.

    Args:
        codes: List of alliance names (may be combined with commas/spaces).

    Returns:
        List of :class:`Alliance` enum values, or ``None`` for empty input.

    Raises:
        ParseError: If any token is not a recognised alliance name.

    """
    if not codes:
        return None

    expanded: list[str] = [
        token.strip().upper().replace(" ", "_").replace("-", "_")
        for item in codes
        for token in _AIRLINE_SEPARATORS.split(item)
        if token.strip()
    ]
    if not expanded:
        raise ParseError(f"No valid alliance names found in: {codes!r}")

    out: list[Alliance] = []
    for name in expanded:
        try:
            out.append(Alliance[name])
        except KeyError as e:
            valid = ", ".join(a.name for a in Alliance)
            raise ParseError(f"Invalid alliance: '{name}'. Valid values: {valid}") from e
    return out


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
        sort_by: Sort option (TOP_FLIGHTS, BEST, CHEAPEST,
            DEPARTURE_TIME, ARRIVAL_TIME, DURATION, EMISSIONS)

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


def parse_currency(currency: str | None) -> str | None:
    """Validate and normalize a currency code string.

    Accepts any ISO 4217 code; emits a warning-free passthrough for codes
    listed in :class:`fli.models.Currency`, and uppercases unknown but
    syntactically-valid 3-letter codes for transparent passthrough.

    Args:
        currency: ISO 4217 currency code or None.

    Returns:
        Uppercased currency code, or None if ``currency`` is None/empty.

    Raises:
        ParseError: If the value is not a valid ISO 4217-style code.

    """
    if currency is None or currency == "":
        return None
    normalized = currency.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ParseError(f"Invalid currency code: '{currency}'. Expected a 3-letter ISO 4217 code.")
    # If recognised, prefer the Currency enum's canonical value.
    try:
        return Currency(normalized).value
    except ValueError:
        return normalized


def parse_emissions(emissions: str) -> EmissionsFilter:
    """Parse an emissions filter string into an EmissionsFilter enum.

    Args:
        emissions: Emissions filter (ALL, LESS)

    Returns:
        The corresponding EmissionsFilter enum member

    Raises:
        ParseError: If the value is not valid

    """
    return resolve_enum(EmissionsFilter, emissions)


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
