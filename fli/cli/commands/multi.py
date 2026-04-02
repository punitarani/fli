"""Multi-city flight search CLI command."""

import re
from typing import Annotated

import typer

from fli.cli.utils import display_flight_results, validate_date, validate_time_range
from fli.core import (
    build_multi_city_segments,
    parse_airlines,
    parse_cabin_class,
    parse_max_stops,
    parse_sort_by,
    resolve_airport,
)
from fli.core.parsers import ParseError
from fli.models import (
    FlightSearchFilters,
    PassengerInfo,
    TimeRestrictions,
)
from fli.search import SearchFlights

LEG_PATTERN = re.compile(r"^([A-Za-z]{3}),([A-Za-z]{3}),(\d{4}-\d{1,2}-\d{1,2})$")


def _parse_leg(value: str) -> tuple[str, str, str]:
    """Parse a leg string in ORIGIN,DEST,DATE format.

    Returns:
        Tuple of (origin, destination, date).

    Raises:
        typer.BadParameter: If the format is invalid.

    """
    match = LEG_PATTERN.match(value)
    if not match:
        raise typer.BadParameter(
            f"Invalid leg format: '{value}'. Expected ORIGIN,DEST,DATE (e.g., SEA,HKG,2026-12-26)"
        )
    return match.group(1).upper(), match.group(2).upper(), match.group(3)


def multi(
    legs: Annotated[
        list[str],
        typer.Option(
            "--leg",
            "-l",
            help="Flight leg in ORIGIN,DEST,DATE format (repeatable, minimum 2)",
        ),
    ],
    departure_window: Annotated[
        str | None,
        typer.Option(
            "--time",
            "-t",
            help="Departure time window in 24h format (e.g., 6-20)",
            callback=validate_time_range,
        ),
    ] = None,
    airlines: Annotated[
        list[str] | None,
        typer.Option(
            "--airlines",
            "-a",
            help="List of airline IATA codes (e.g., BA KL)",
        ),
    ] = None,
    cabin_class: Annotated[
        str,
        typer.Option(
            "--class",
            "-c",
            help="Cabin class (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)",
        ),
    ] = "ECONOMY",
    max_stops: Annotated[
        str,
        typer.Option(
            "--stops",
            "-s",
            help="Maximum stops (ANY, 0 for non-stop, 1 for one stop, 2+ for two stops)",
        ),
    ] = "ANY",
    sort_by: Annotated[
        str,
        typer.Option(
            "--sort",
            "-o",
            help="Sort results by (CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME)",
        ),
    ] = "CHEAPEST",
):
    """Search for multi-city flights with multiple legs.

    Each leg specifies an origin, destination, and date. At least two legs are required.

    Example:
        fli multi --leg SEA,HKG,2026-12-26 --leg PEK,SEA,2027-01-02
        fli multi -l SEA,NRT,2026-12-26 -l NRT,HKG,2026-12-30 -l HKG,SEA,2027-01-05 -c BUSINESS

    """
    try:
        if len(legs) < 2:
            typer.echo("Error: multi-city search requires at least 2 legs")
            raise typer.Exit(1)

        # Parse and validate each leg
        parsed_legs = []
        for leg_str in legs:
            origin, destination, date = _parse_leg(leg_str)
            date = validate_date(None, None, date)
            origin_airport = resolve_airport(origin)
            destination_airport = resolve_airport(destination)
            parsed_legs.append((origin_airport, destination_airport, date))

        # Parse shared filter parameters
        seat_type = parse_cabin_class(cabin_class)
        stops = parse_max_stops(max_stops)
        parsed_airlines = parse_airlines(airlines)
        sort = parse_sort_by(sort_by)

        # Build time restrictions
        time_restrictions = None
        if departure_window:
            time_restrictions = TimeRestrictions(
                earliest_departure=departure_window[0],
                latest_departure=departure_window[1],
            )

        # Build multi-city segments using shared builder
        segments, trip_type = build_multi_city_segments(
            legs=parsed_legs,
            time_restrictions=time_restrictions,
        )

        # Create search filters
        filters = FlightSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=segments,
            stops=stops,
            seat_type=seat_type,
            airlines=parsed_airlines,
            sort_by=sort,
        )

        # Perform search
        search_client = SearchFlights()
        results = search_client.search(filters)

        if not results:
            typer.echo("No flights found.")
            raise typer.Exit(1)

        display_flight_results(results)

    except ParseError as e:
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
    except (AttributeError, ValueError) as e:
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
