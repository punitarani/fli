"""Flight search CLI command."""

from typing import Annotated, Any

import typer

from fli.cli.enums import OutputFormat
from fli.cli.utils import (
    build_json_error_response,
    build_json_success_response,
    display_flight_results,
    emit_json,
    normalize_cli_date,
    normalize_cli_time_range,
    serialize_flight_result,
)
from fli.core import (
    build_flight_segments,
    parse_airlines,
    parse_cabin_class,
    parse_emissions,
    parse_max_stops,
    parse_sort_by,
    resolve_airport,
)
from fli.core.parsers import ParseError
from fli.models import (
    BagsFilter,
    FlightSearchFilters,
    LayoverRestrictions,
    PassengerInfo,
)
from fli.search import SearchFlights


def _search_flights_core(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    departure_window: str | tuple[int, int] | None = None,
    airlines: list[str] | None = None,
    cabin_class: str = "ECONOMY",
    max_stops: str = "ANY",
    sort_by: str = "CHEAPEST",
    exclude_basic_economy: bool = False,
    layover: list[str] | None = None,
    emissions: str = "ALL",
    checked_bags: int = 0,
    carry_on: bool = False,
    all_results: bool = True,
    output_format: OutputFormat = OutputFormat.TEXT,
) -> None:
    """Core flight search functionality."""
    query: dict[str, Any] = {
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": departure_date,
        "return_date": return_date,
        "departure_window": None,
        "airlines": [airline.upper() for airline in airlines] if airlines else None,
        "cabin_class": cabin_class.upper(),
        "max_stops": max_stops.upper(),
        "sort_by": sort_by.upper(),
    }

    try:
        departure_date = normalize_cli_date(departure_date)
        return_date = normalize_cli_date(return_date)
        departure_window = normalize_cli_time_range(departure_window)
        query["departure_date"] = departure_date
        query["return_date"] = return_date
        query["departure_window"] = (
            f"{departure_window[0]}-{departure_window[1]}" if departure_window else None
        )

        # Parse parameters using shared utilities
        origin_airport = resolve_airport(origin)
        destination_airport = resolve_airport(destination)
        seat_type = parse_cabin_class(cabin_class)
        stops = parse_max_stops(max_stops)
        parsed_airlines = parse_airlines(airlines)
        sort = parse_sort_by(sort_by)
        emissions_filter = parse_emissions(emissions)

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

        # Parse layover airports
        layover_restrictions = None
        if layover:
            layover_airports = [resolve_airport(code) for code in layover]
            layover_restrictions = LayoverRestrictions(airports=layover_airports)

        # Build bags filter
        bags_filter = None
        if checked_bags > 0 or carry_on:
            bags_filter = BagsFilter(checked_bags=checked_bags, carry_on=carry_on)

        # Create search filters
        filters = FlightSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=segments,
            stops=stops,
            seat_type=seat_type,
            airlines=parsed_airlines,
            sort_by=sort,
            exclude_basic_economy=exclude_basic_economy,
            layover_restrictions=layover_restrictions,
            emissions=emissions_filter,
            bags=bags_filter,
            show_all_results=all_results,
        )

        # Perform search
        search_client = SearchFlights()
        results = search_client.search(filters)

        if not results:
            if output_format == OutputFormat.JSON:
                emit_json(
                    build_json_success_response(
                        search_type="flights",
                        trip_type=trip_type,
                        query=query,
                        results_key="flights",
                        results=[],
                    )
                )
                return

            typer.echo("No flights found.")
            raise typer.Exit(1)

        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_success_response(
                    search_type="flights",
                    trip_type=trip_type,
                    query=query,
                    results_key="flights",
                    results=[serialize_flight_result(result) for result in results],
                )
            )
            return

        display_flight_results(results)

    except ParseError as e:
        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_error_response(
                    search_type="flights",
                    message=str(e),
                    query=query,
                )
            )
            raise typer.Exit(1) from e

        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
    except (AttributeError, ValueError) as e:
        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_error_response(
                    search_type="flights",
                    message=str(e),
                    error_type="search_error",
                    query=query,
                )
            )
            raise typer.Exit(1) from e

        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e


def flights(
    origin: Annotated[str, typer.Argument(help="Departure airport IATA code (e.g., JFK)")],
    destination: Annotated[str, typer.Argument(help="Arrival airport IATA code (e.g., LHR)")],
    departure_date: Annotated[str, typer.Argument(help="Travel date (YYYY-MM-DD)")],
    return_date: Annotated[
        str | None,
        typer.Option(
            "--return",
            "-r",
            help="Return date (YYYY-MM-DD)",
        ),
    ] = None,
    departure_window: Annotated[
        str | None,
        typer.Option(
            "--time",
            "-t",
            help="Departure time window in 24h format (e.g., 6-20)",
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
            help="Sort by: TOP_FLIGHTS, BEST, CHEAPEST, DEPARTURE_TIME,"
            " ARRIVAL_TIME, DURATION, EMISSIONS",
        ),
    ] = "CHEAPEST",
    exclude_basic_economy: Annotated[
        bool,
        typer.Option(
            "--exclude-basic",
            "-e",
            help="Exclude basic economy fares",
        ),
    ] = False,
    layover: Annotated[
        list[str] | None,
        typer.Option(
            "--layover",
            "-l",
            help="Restrict layover to these airports (e.g., -l ORD -l MDW)",
        ),
    ] = None,
    emissions: Annotated[
        str,
        typer.Option(
            "--emissions",
            help="Filter by emissions level (ALL, LESS)",
        ),
    ] = "ALL",
    checked_bags: Annotated[
        int,
        typer.Option(
            "--bags",
            "-b",
            help="Number of checked bags to include in price (0, 1, or 2)",
            min=0,
            max=2,
        ),
    ] = 0,
    carry_on: Annotated[
        bool,
        typer.Option(
            "--carry-on",
            help="Include carry-on bag fee in price",
        ),
    ] = False,
    all_results: Annotated[
        bool,
        typer.Option(
            "--all/--no-all",
            help="Show all available results (default) or only ~30 curated results",
        ),
    ] = True,
    output_format: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            help="Output format: text or json",
            case_sensitive=False,
        ),
    ] = OutputFormat.TEXT,
):
    """Search for flights on a specific date.

    Example:
        fli flights JFK LHR 2025-10-25 --time 6-20 --airlines BA KL --stops NON_STOP
        fli flights JFK LHR 2025-10-25 --format json
        fli flights JFK LHR 2025-10-25 --exclude-basic
        fli flights JFK LAX 2025-10-25 --bags 1 --carry-on
        fli flights JFK LAX 2025-10-25 --emissions LESS
        fli flights JFK LAX 2025-10-25 --all

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
        exclude_basic_economy=exclude_basic_economy,
        layover=layover,
        emissions=emissions,
        checked_bags=checked_bags,
        carry_on=carry_on,
        all_results=all_results,
        output_format=output_format,
    )
