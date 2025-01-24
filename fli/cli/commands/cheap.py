from datetime import datetime, timedelta
from typing import Annotated

import typer

from fli.cli.enums import DayOfWeek
from fli.cli.utils import (
    display_date_results,
    filter_dates_by_days,
    parse_airlines,
    parse_stops,
    parse_trip_type,
    validate_date,
    validate_time_range,
)
from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
    TimeRestrictions,
    TripType,
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
    duration: Annotated[
        int,
        typer.Option(
            "--duration",
            "-d",
            help="Duration of trip in days",
        ),
    ] = 3,
    airlines: Annotated[
        list[str] | None,
        typer.Option(
            "--airlines",
            "-a",
            help="List of airline codes (e.g., BA KL)",
        ),
    ] = None,
    trip_type: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help="Trip type (ONEWAY, ROUND)",
        ),
    ] = "ONEWAY",
    stops: Annotated[
        str,
        typer.Option(
            "--stops",
            "-s",
            help="Maximum number of stops (ANY, 0 for non-stop, 1 for one stop, 2+ for two stops)",
        ),
    ] = "ANY",
    seat: Annotated[
        str,
        typer.Option(
            "--class",
            "-c",
            help="Seat type (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)",
        ),
    ] = "ECONOMY",
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
    time: Annotated[
        str | None,
        typer.Option(
            "--time",
            "-time",
            help="Time range in 24h format (e.g., 6-20)",
            callback=validate_time_range,
        ),
    ] = None,
):
    """Find the cheapest dates to fly between two airports.

    Example:
        fli cheap LAX MIA --seat BUSINESS --stops NON_STOP --friday

    """
    try:
        # Parse parameters
        departure_airport = getattr(Airport, from_airport.upper())
        arrival_airport = getattr(Airport, to_airport.upper())
        trip_type = parse_trip_type(trip_type)
        max_stops = parse_stops(stops)
        seat_type = getattr(SeatType, seat.upper())
        airlines = parse_airlines(airlines)

        # Parse time restrictions
        time_restrictions = None
        if time:
            if isinstance(time, tuple):
                start_hour, end_hour = time
            else:
                start_hour, end_hour = map(int, time.split("-"))
            time_restrictions = TimeRestrictions(
                earliest_departure=start_hour,
                latest_departure=end_hour,
                earliest_arrival=None,
                latest_arrival=None,
            )

        # Create flight segment
        flight_segment = FlightSegment(
            departure_airport=[[departure_airport, 0]],
            arrival_airport=[[arrival_airport, 0]],
            travel_date=from_date,
            time_restrictions=time_restrictions,
        )

        # Handle round trip
        if trip_type == TripType.ROUND_TRIP:
            return_flight_segment = FlightSegment(
                departure_airport=[[arrival_airport, 0]],
                arrival_airport=[[departure_airport, 0]],
                travel_date=(
                    datetime.strptime(flight_segment.travel_date, "%Y-%m-%d")
                    + timedelta(days=duration)
                ).strftime("%Y-%m-%d"),
                time_restrictions=time_restrictions,
            )

            flight_segments = [flight_segment, return_flight_segment]
        else:
            flight_segments = [flight_segment]

        # Create search filters
        filters = DateSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=flight_segments,
            stops=max_stops,
            seat_type=seat_type,
            airlines=airlines,
            from_date=from_date,
            to_date=to_date,
            duration=duration if trip_type == TripType.ROUND_TRIP else None,
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

        if selected_days:
            dates = filter_dates_by_days(dates, selected_days, trip_type)

        if not dates:
            typer.echo("No flights found for the selected days.")
            raise typer.Exit(1)

        # Sort dates by price if sort flag is enabled
        if sort:
            dates.sort(key=lambda x: x.price)

        # Display results
        display_date_results(dates, trip_type)

    except (AttributeError, ValueError) as e:
        if "module 'fli.search' has no attribute 'SearchDates'" in str(e):
            raise
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
