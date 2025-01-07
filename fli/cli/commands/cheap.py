from datetime import datetime, timedelta

import typer
from typing_extensions import Annotated

from fli.cli.enums import DayOfWeek
from fli.cli.utils import display_date_results, filter_dates_by_days, parse_stops, validate_date
from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
)
from fli.search import SearchDates


def cheap(
    from_airport: Annotated[str, typer.Argument(help="Departure airport code (e.g., JFK)")],
    to_airport: Annotated[str, typer.Argument(help="Arrival airport code (e.g., LHR)")],
    from_date: Annotated[
        str, typer.Option("--from", help="Start date (YYYY-MM-DD)", callback=validate_date)
    ] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
    to_date: Annotated[
        str, typer.Option("--to", help="End date (YYYY-MM-DD)", callback=validate_date)
    ] = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d"),
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
            help="Maximum number of stops (ANY, 0 for non-stop, 1 for one stop, 2+ for two stops)",
        ),
    ] = "ANY",
    sort: Annotated[
        bool,
        typer.Option(
            "--sort",
            help="Sort results by price (lowest to highest)",
        ),
    ] = False,
    monday: Annotated[
        bool,
        typer.Option(
            "--monday",
            "-mon",
            help="Include Mondays in results",
        ),
    ] = False,
    tuesday: Annotated[
        bool,
        typer.Option(
            "--tuesday",
            "-tue",
            help="Include Tuesdays in results",
        ),
    ] = False,
    wednesday: Annotated[
        bool,
        typer.Option(
            "--wednesday",
            "-wed",
            help="Include Wednesdays in results",
        ),
    ] = False,
    thursday: Annotated[
        bool,
        typer.Option(
            "--thursday",
            "-thu",
            help="Include Thursdays in results",
        ),
    ] = False,
    friday: Annotated[
        bool,
        typer.Option(
            "--friday",
            "-fri",
            help="Include Fridays in results",
        ),
    ] = False,
    saturday: Annotated[
        bool,
        typer.Option(
            "--saturday",
            "-sat",
            help="Include Saturdays in results",
        ),
    ] = False,
    sunday: Annotated[
        bool,
        typer.Option(
            "--sunday",
            "-sun",
            help="Include Sundays in results",
        ),
    ] = False,
):
    """
    Find the cheapest dates to fly between two airports.

    Examples:\n
        fli cheap JFK LHR\n
        fli cheap SFO NYC --from 2025-01-01 --to 2025-02-01\n
        fli cheap LAX MIA --seat BUSINESS --stops NON_STOP\n
        fli cheap JFK LHR --monday --friday  # Only show Monday and Friday flights\n
        fli cheap SFO NYC --monday --wednesday --friday  # Show weekday options
    """
    try:
        # Parse parameters
        departure_airport = getattr(Airport, from_airport.upper())
        arrival_airport = getattr(Airport, to_airport.upper())
        seat_type = getattr(SeatType, seat.upper())
        max_stops = parse_stops(stops)

        # Create flight segment
        flight_segment = FlightSegment(
            departure_airport=[[departure_airport, 0]],
            arrival_airport=[[arrival_airport, 0]],
            travel_date=from_date,
        )

        # Create search filters
        filters = DateSearchFilters(
            departure_airport=departure_airport,
            arrival_airport=arrival_airport,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[flight_segment],
            seat_type=seat_type,
            stops=max_stops,
            from_date=from_date,
            to_date=to_date,
        )

        # Perform search
        search_client = SearchDates()
        dates = search_client.search(filters)

        if not dates:
            typer.echo("No flights found for these dates.")
            raise typer.Exit(1)

        # Filter by days if any day filters are specified
        selected_days = []
        if monday:
            selected_days.append(DayOfWeek.MONDAY)
        if tuesday:
            selected_days.append(DayOfWeek.TUESDAY)
        if wednesday:
            selected_days.append(DayOfWeek.WEDNESDAY)
        if thursday:
            selected_days.append(DayOfWeek.THURSDAY)
        if friday:
            selected_days.append(DayOfWeek.FRIDAY)
        if saturday:
            selected_days.append(DayOfWeek.SATURDAY)
        if sunday:
            selected_days.append(DayOfWeek.SUNDAY)

        dates = filter_dates_by_days(dates, selected_days)

        if not dates:
            typer.echo("No flights found for the selected days.")
            raise typer.Exit(1)

        # Sort dates by price if sort flag is enabled
        if sort:
            dates.sort(key=lambda x: x.price)

        # Display results
        display_date_results(dates)

    except (AttributeError, ValueError) as e:
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1)
