#!/usr/bin/env python3

from datetime import datetime
from typing import List, Optional

import typer
from click import Context, Parameter
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from typing_extensions import Annotated

from fli.models import Airline, Airport, MaxStops, PassengerInfo, SeatType, SortBy
from fli.search import Search, SearchFilters

app = typer.Typer(
    help="Search for flights using Google Flights data",
    add_completion=True,
)
console = Console()


def format_airport(airport: Airport) -> str:
    """Format airport code and name (first two words)."""
    name_parts = airport.value.split()[:3]  # Get first three words
    name = " ".join(name_parts)
    return f"{airport.name} ({name})"


def validate_time_range(
    ctx: Context, param: Parameter, value: Optional[str]
) -> Optional[tuple[int, int]]:
    """Validate and parse time range in format 'start-end' (24h format)."""
    if not value:
        return None

    try:
        start, end = map(int, value.split("-"))
        if not (0 <= start <= 23 and 0 <= end <= 23):
            raise ValueError
        return start, end
    except ValueError:
        raise typer.BadParameter("Time range must be in format 'start-end' (e.g., 6-20)")


def validate_date(ctx: Context, param: Parameter, value: str) -> str:
    """Validate date format."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError:
        raise typer.BadParameter("Date must be in YYYY-MM-DD format")


def parse_airlines(airlines: Optional[List[str]]) -> Optional[List[Airline]]:
    """Parse airlines from list of airline codes."""
    if not airlines:
        return None

    try:
        return [
            getattr(Airline, airline.strip().upper()) for airline in airlines if airline.strip()
        ]
    except AttributeError as e:
        raise typer.BadParameter(f"Invalid airline code: {str(e)}")


def filter_flights_by_time(flights: list, start_hour: int, end_hour: int) -> list:
    """Filter flights by departure time range."""
    return [
        flight
        for flight in flights
        if any(start_hour <= leg.departure_datetime.hour <= end_hour for leg in flight.legs)
    ]


def filter_flights_by_airlines(flights: list, airlines: List[Airline]) -> list:
    """Filter flights by specified airlines."""
    return [flight for flight in flights if any(leg.airline in airlines for leg in flight.legs)]


def format_duration(minutes: int) -> str:
    """Format duration in minutes to hours and minutes."""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def display_flight_results(flights: list):
    """Display flight results in a beautiful format."""
    if not flights:
        console.print(Panel("No flights found matching your criteria", style="red"))
        return

    for i, flight in enumerate(flights, 1):
        # Create main flight info table
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("Label", style="blue")
        table.add_column("Value", style="green")

        table.add_row("Price", f"${flight.price:,.2f}")
        table.add_row("Duration", format_duration(flight.duration))
        table.add_row("Stops", str(flight.stops))

        # Create segments table
        segments = Table(title="Flight Segments", box=box.ROUNDED)
        segments.add_column("Airline", style="cyan")
        segments.add_column("Flight", style="magenta")
        segments.add_column("From", style="yellow", width=30)
        segments.add_column("Departure", style="green")
        segments.add_column("To", style="yellow", width=30)
        segments.add_column("Arrival", style="green")

        for leg in flight.legs:
            segments.add_row(
                leg.airline.value,
                leg.flight_number,
                format_airport(leg.departure_airport),
                leg.departure_datetime.strftime("%H:%M %d-%b"),
                format_airport(leg.arrival_airport),
                leg.arrival_datetime.strftime("%H:%M %d-%b"),
            )

        # Display in a panel
        console.print(
            Panel(
                Group(
                    Text(f"Flight Option {i}", style="bold blue"),
                    Text(""),
                    table,
                    Text(""),
                    segments,
                ),
                title=f"[bold]Flight {i} of {len(flights)}[/bold]",
                border_style="blue",
                box=box.ROUNDED,
            )
        )
        console.print()


@app.command()
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
    with console.status("[bold green]Searching for flights...") as status:
        try:
            # Parse parameters
            departure_airport = getattr(Airport, from_airport.upper())
            arrival_airport = getattr(Airport, to_airport.upper())
            seat_type = getattr(SeatType, seat.upper())
            max_stops = getattr(MaxStops, stops.upper())
            sort_by = getattr(SortBy, sort.upper())

            # Create search filters
            filters = SearchFilters(
                departure_airport=departure_airport,
                arrival_airport=arrival_airport,
                departure_date=date,
                passenger_info=PassengerInfo(adults=1),
                seat_type=seat_type,
                stops=max_stops,
                sort_by=sort_by,
            )

            # Perform search
            search_client = Search()
            flights = search_client.search(filters)

            if not flights:
                console.print(Panel("No flights found.", style="red"))
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
            console.print(f"[red]Error:[/red] {str(e)}")
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
