"""Date search CLI command for finding cheapest travel dates."""

from datetime import datetime, timedelta
from typing import Annotated

import typer

from fli.cli.enums import DayOfWeek
from fli.cli.utils import (
    display_date_results,
    filter_dates_by_days,
    validate_date,
    validate_time_range,
)
from fli.core import (
    build_date_search_segments,
    parse_airlines,
    parse_cabin_class,
    parse_max_stops,
    resolve_airport,
)
from fli.core.parsers import ParseError
from fli.models import (
    DateSearchFilters,
    PassengerInfo,
    TimeRestrictions,
    TripType,
)
from fli.search import SearchDates


def dates(
    origin: Annotated[str, typer.Argument(help="Departure airport IATA code (e.g., JFK)")],
    destination: Annotated[str, typer.Argument(help="Arrival airport IATA code (e.g., LHR)")],
    start_date: Annotated[
        str,
        typer.Option("--from", help="Start date (YYYY-MM-DD)", callback=validate_date),
    ] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
    end_date: Annotated[
        str, typer.Option("--to", help="End date (YYYY-MM-DD)", callback=validate_date)
    ] = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d"),
    trip_duration: Annotated[
        int,
        typer.Option(
            "--duration",
            "-d",
            help="Trip duration in days",
        ),
    ] = 3,
    airlines: Annotated[
        list[str] | None,
        typer.Option(
            "--airlines",
            "-a",
            help="List of airline IATA codes (e.g., BA KL)",
        ),
    ] = None,
    is_round_trip: Annotated[
        bool,
        typer.Option(
            "--round",
            "-R",
            help="Search for round-trip flights",
        ),
    ] = False,
    max_stops: Annotated[
        str,
        typer.Option(
            "--stops",
            "-s",
            help="Maximum stops (ANY, 0 for non-stop, 1 for one stop, 2+ for two stops)",
        ),
    ] = "ANY",
    cabin_class: Annotated[
        str,
        typer.Option(
            "--class",
            "-c",
            help="Cabin class (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)",
        ),
    ] = "ECONOMY",
    sort_by_price: Annotated[
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
    departure_window: Annotated[
        str | None,
        typer.Option(
            "--time",
            "-time",
            help="Departure time window in 24h format (e.g., 6-20)",
            callback=validate_time_range,
        ),
    ] = None,
):
    """Find the cheapest dates to fly between two airports.

    Example:
        fli dates LAX MIA --class BUSINESS --stops NON_STOP --friday

    """
    try:
        # Parse parameters using shared utilities
        origin_airport = resolve_airport(origin)
        destination_airport = resolve_airport(destination)
        trip_type = TripType.ROUND_TRIP if is_round_trip else TripType.ONE_WAY
        stops = parse_max_stops(max_stops)
        seat_type = parse_cabin_class(cabin_class)
        parsed_airlines = parse_airlines(airlines)

        # Build time restrictions from tuple
        time_restrictions = None
        if departure_window:
            if isinstance(departure_window, tuple):
                start_hour, end_hour = departure_window
            else:
                start_hour, end_hour = map(int, departure_window.split("-"))
            time_restrictions = TimeRestrictions(
                earliest_departure=start_hour,
                latest_departure=end_hour,
                earliest_arrival=None,
                latest_arrival=None,
            )

        # Build flight segments using shared builder
        segments, trip_type = build_date_search_segments(
            origin=origin_airport,
            destination=destination_airport,
            start_date=start_date,
            trip_duration=trip_duration,
            is_round_trip=is_round_trip,
            time_restrictions=time_restrictions,
        )

        # Create search filters
        filters = DateSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=segments,
            stops=stops,
            seat_type=seat_type,
            airlines=parsed_airlines,
            from_date=start_date,
            to_date=end_date,
            duration=trip_duration if trip_type == TripType.ROUND_TRIP else None,
        )

        # Perform search
        search_client = SearchDates()
        results = search_client.search(filters)

        if not results:
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

        if selected_days:
            results = filter_dates_by_days(results, selected_days, trip_type)

        if not results:
            typer.echo("No flights found for the selected days.")
            raise typer.Exit(1)

        # Sort dates by price if sort flag is enabled
        if sort_by_price:
            results.sort(key=lambda x: x.price)

        # Display results
        display_date_results(results, trip_type)

    except ParseError as e:
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
    except (AttributeError, ValueError) as e:
        if "module 'fli.search' has no attribute 'SearchDates'" in str(e):
            raise
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
