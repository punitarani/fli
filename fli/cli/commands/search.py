from typing import Annotated

import typer

from fli.cli.utils import (
    display_flight_results,
    parse_airlines,
    parse_stops,
    validate_date,
    validate_time_range,
)
from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.models.google_flights.base import TimeRestrictions, TripType
from fli.search import SearchFlights


def search_flights(
    trip_type: TripType,
    from_airport: str,
    to_airport: str,
    date: str,
    return_date: str | None = None,
    time: tuple[int, int] | None = None,
    airlines: list[str] | None = None,
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
        max_stops = parse_stops(stops)
        airlines = parse_airlines(airlines)
        sort_by = getattr(SortBy, sort.upper())

        time_restrictions = None
        if time:
            start_hour, end_hour = time
            time_restrictions = TimeRestrictions(
                earliest_departure=start_hour, latest_departure=end_hour
            )

        # Create flight segments
        flight_segments = [
            FlightSegment(
                departure_airport=[[departure_airport, 0]],
                arrival_airport=[[arrival_airport, 0]],
                travel_date=date,
                time_restrictions=time_restrictions,
            )
        ]
        if return_date:
            flight_segments.append(
                FlightSegment(
                    departure_airport=[[arrival_airport, 0]],
                    arrival_airport=[[departure_airport, 0]],
                    travel_date=return_date,
                    time_restrictions=time_restrictions,
                )
            )

        # Create search filters
        filters = FlightSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=flight_segments,
            stops=max_stops,
            seat_type=seat_type,
            airlines=airlines,
            sort_by=sort_by,
        )

        # Perform search
        search_client = SearchFlights()
        flights = search_client.search(filters)

        if not flights:
            typer.echo("No flights found.")
            raise typer.Exit(1)

        # Display results
        display_flight_results(flights)

    except (AttributeError, ValueError) as e:
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e


def search(
    from_airport: Annotated[str, typer.Argument(help="Departure airport code (e.g., JFK)")],
    to_airport: Annotated[str, typer.Argument(help="Arrival airport code (e.g., LHR)")],
    date: Annotated[str, typer.Argument(help="Travel date (YYYY-MM-DD)", callback=validate_date)],
    return_date: Annotated[
        str | None,
        typer.Option(
            "--return",
            "-r",
            help="Return date (YYYY-MM-DD)",
            callback=validate_date,
        ),
    ] = None,
    time: Annotated[
        str | None,
        typer.Option(
            "--time",
            "-t",
            help="Time range in 24h format (e.g., 6-20)",
            callback=validate_time_range,
        ),
    ] = None,
    airlines: Annotated[
        list[str] | None,
        typer.Option(
            "--airlines",
            "-a",
            help="List of airline codes (e.g., BA KL)",
        ),
    ] = None,
    seat: Annotated[
        str,
        typer.Option(
            "--class",
            "-c",
            help="Seat type (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)",
        ),
    ] = "ECONOMY",
    stops: Annotated[
        str,
        typer.Option(
            "--stops",
            "-s",
            help="Maximum number of stops (ANY, 0 for non-stop, 1 for one stop, 2+ for two stops)",
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
    """Search for flights with flexible filtering options.

    Example:
        fli search JFK LHR 2025-10-25 --time 6-20 --airlines BA KL --stops NON_STOP

    """
    search_flights(
        trip_type=TripType.ROUND_TRIP if return_date else TripType.ONE_WAY,
        from_airport=from_airport,
        to_airport=to_airport,
        date=date,
        return_date=return_date,
        time=time,
        airlines=airlines,
        seat=seat,
        stops=stops,
        sort=sort,
    )
