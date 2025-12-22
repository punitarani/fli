"""Flight search CLI command."""

from typing import Annotated

import typer

from fli.cli.utils import display_flight_results, validate_date, validate_time_range
from fli.core import (
    build_flight_segments,
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
)
from fli.search import SearchFlights


def _search_flights_core(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    departure_window: tuple[int, int] | None = None,
    airlines: list[str] | None = None,
    cabin_class: str = "ECONOMY",
    max_stops: str = "ANY",
    sort_by: str = "CHEAPEST",
):
    """Core flight search functionality."""
    try:
        # Parse parameters using shared utilities
        origin_airport = resolve_airport(origin)
        destination_airport = resolve_airport(destination)
        seat_type = parse_cabin_class(cabin_class)
        stops = parse_max_stops(max_stops)
        parsed_airlines = parse_airlines(airlines)
        sort = parse_sort_by(sort_by)

        # Build time restrictions from tuple
        time_restrictions = None
        if departure_window:
            from fli.models import TimeRestrictions

            time_restrictions = TimeRestrictions(
                earliest_departure=departure_window[0],
                latest_departure=departure_window[1],
            )

        # Create flight segments using shared builder
        segments, trip_type = build_flight_segments(
            origin=origin_airport,
            destination=destination_airport,
            departure_date=departure_date,
            return_date=return_date,
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

        # Display results
        display_flight_results(results)

    except ParseError as e:
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
    except (AttributeError, ValueError) as e:
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e


def flights(
    origin: Annotated[str, typer.Argument(help="Departure airport IATA code (e.g., JFK)")],
    destination: Annotated[str, typer.Argument(help="Arrival airport IATA code (e.g., LHR)")],
    departure_date: Annotated[
        str, typer.Argument(help="Travel date (YYYY-MM-DD)", callback=validate_date)
    ],
    return_date: Annotated[
        str | None,
        typer.Option(
            "--return",
            "-r",
            help="Return date (YYYY-MM-DD)",
            callback=validate_date,
        ),
    ] = None,
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
    """Search for flights on a specific date.

    Example:
        fli flights JFK LHR 2025-10-25 --time 6-20 --airlines BA KL --stops NON_STOP

    """
    _search_flights_core(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        departure_window=departure_window,
        airlines=airlines,
        cabin_class=cabin_class,
        max_stops=max_stops,
        sort_by=sort_by,
    )
