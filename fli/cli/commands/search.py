from typing import List, Optional

import typer
from typing_extensions import Annotated

from fli.cli.utils import (
    display_flight_results,
    filter_flights_by_airlines,
    filter_flights_by_time,
    parse_airlines,
    validate_date,
    validate_time_range,
)
from fli.models import Airport, MaxStops, PassengerInfo, SeatType, SortBy
from fli.search import SearchFlights, SearchFlightsFilters


def search_flights(
    from_airport: str,
    to_airport: str,
    date: str,
    time: Optional[tuple[int, int]] = None,
    airlines: Optional[List[str]] = None,
    seat: str = "ECONOMY",
    stops: str = "ANY",
    sort: str = "CHEAPEST",
):
    """Core flight search functionality."""
    try:
        # Parse parameters
        departure_airport = getattr(Airport, from_airport.upper())
        arrival_airport = getattr(Airport, to_airport.upper())
        seat_type = getattr(SeatType, seat.upper())
        max_stops = getattr(MaxStops, stops.upper())
        sort_by = getattr(SortBy, sort.upper())

        # Create search filters
        filters = SearchFlightsFilters(
            departure_airport=departure_airport,
            arrival_airport=arrival_airport,
            departure_date=date,
            passenger_info=PassengerInfo(adults=1),
            seat_type=seat_type,
            stops=max_stops,
            sort_by=sort_by,
        )

        # Perform search
        search_client = SearchFlights()
        flights = search_client.search(filters)

        if not flights:
            typer.echo("No flights found.")
            raise typer.Exit(1)

        # Apply time filter if specified
        if time:
            start_hour, end_hour = time
            flights = filter_flights_by_time(flights, start_hour, end_hour)

        # Apply airline filter if specified
        airline_list = parse_airlines(airlines)
        if airline_list:
            flights = filter_flights_by_airlines(flights, airline_list)

        # Display results
        display_flight_results(flights)

    except (AttributeError, ValueError) as e:
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1)


def search(
    from_airport: Annotated[str, typer.Argument(help="Departure airport code (e.g., JFK)")],
    to_airport: Annotated[str, typer.Argument(help="Arrival airport code (e.g., LHR)")],
    date: Annotated[str, typer.Argument(help="Travel date (YYYY-MM-DD)", callback=validate_date)],
    time: Annotated[
        Optional[str],
        typer.Option(
            "--time",
            "-t",
            help="Time range in 24h format (e.g., 6-20)",
            callback=validate_time_range,
        ),
    ] = None,
    airlines: Annotated[
        Optional[List[str]],
        typer.Option(
            "--airlines",
            "-a",
            help="List of airline codes (e.g., BA KL)",
        ),
    ] = None,
    seat: Annotated[
        str,
        typer.Option(
            "--seat",
            "-s",
            help="Seat type (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)",
        ),
    ] = "ECONOMY",
    stops: Annotated[
        str,
        typer.Option(
            "--stops",
            "-x",
            help="Maximum number of stops (ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS)",
        ),
    ] = "ANY",
    sort: Annotated[
        str,
        typer.Option(
            "--sort",
            "-o",
            help="Sort results by (CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME)",
        ),
    ] = "CHEAPEST",
):
    """
    Search for flights with flexible filtering options.

    Examples:\n
        fli search JFK LHR 2025-10-25 --time 6-20 --airlines BA KL\n
        fli search SFO NYC 2025-11-01 -t 9-17 --stops NON_STOP --sort DURATION\n
        fli search LAX MIA 2025-12-25 --seat BUSINESS
    """
    search_flights(
        from_airport=from_airport,
        to_airport=to_airport,
        date=date,
        time=time,
        airlines=airlines,
        seat=seat,
        stops=stops,
        sort=sort,
    )
