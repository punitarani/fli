"""CLI utility functions for display and validation."""

import json
from typing import Any

import plotext as plt
import typer
from click import Context, Parameter
from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fli.cli.console import console
from fli.cli.enums import DayOfWeek
from fli.core import format_price, format_price_axis_label
from fli.core.builders import normalize_date
from fli.core.parsers import ParseError
from fli.core.parsers import parse_airlines as core_parse_airlines
from fli.core.parsers import parse_max_stops as core_parse_max_stops
from fli.models import Airline, Airport, MaxStops, TripType

DEFAULT_CURRENCY = "USD"


def validate_date(ctx: Context, param: Parameter, value: str) -> str | None:
    """Validate date format for typer callbacks."""
    if value is None:
        return None

    try:
        return normalize_date(value)
    except ValueError as e:
        raise typer.BadParameter("Date must be in YYYY-MM-DD format") from e


def validate_time_range(
    ctx: Context, param: Parameter, value: str | None
) -> tuple[int, int] | None:
    """Validate and parse time range in format 'start-end' (24h format) for typer callbacks."""
    if not value:
        return None

    try:
        start, end = map(int, value.split("-"))
        if not (0 <= start <= 23 and 0 <= end <= 23):
            raise ValueError
        return start, end
    except ValueError as e:
        raise typer.BadParameter("Time range must be in format 'start-end' (e.g., 6-20)") from e


def normalize_cli_date(value: str | None) -> str | None:
    """Normalize a CLI date value or raise a parse error."""
    if value is None:
        return None

    try:
        return normalize_date(value)
    except ValueError as e:
        raise ParseError("Date must be in YYYY-MM-DD format") from e


def normalize_cli_time_range(value: str | tuple[int, int] | None) -> tuple[int, int] | None:
    """Normalize a CLI time range or raise a parse error."""
    if value is None:
        return None

    if isinstance(value, tuple):
        start, end = value
    else:
        try:
            start, end = map(int, value.split("-"))
        except ValueError as e:
            raise ParseError("Time range must be in format 'start-end' (e.g., 6-20)") from e

    if not (0 <= start <= 23 and 0 <= end <= 23):
        raise ParseError("Time range must be in format 'start-end' (e.g., 6-20)")

    return start, end


def parse_airlines(airlines: list[str] | None) -> list[Airline] | None:
    """Parse airlines from list of airline codes.

    Delegates to core parser but wraps errors for CLI.
    """
    if not airlines:
        return None

    try:
        return core_parse_airlines(airlines)
    except ParseError as e:
        raise typer.BadParameter(str(e)) from e


def parse_stops(stops: str) -> MaxStops:
    """Convert stops parameter to MaxStops enum.

    Delegates to core parser but wraps errors for CLI.
    """
    try:
        return core_parse_max_stops(stops)
    except ParseError as e:
        raise typer.BadParameter(str(e)) from e


def parse_trip_type(trip_type: str) -> TripType:
    """Convert trip type parameter to TripType enum."""
    match trip_type.upper():
        case "ONEWAY" | "ONE_WAY":
            return TripType.ONE_WAY
        case "ROUND" | "ROUND_TRIP":
            return TripType.ROUND_TRIP
        case _:
            raise typer.BadParameter(f"Invalid trip type: {trip_type}")


def filter_flights_by_time(flights: list, start_hour: int, end_hour: int) -> list:
    """Filter flights by departure time range."""
    return [
        flight
        for flight in flights
        if any(start_hour <= leg.departure_datetime.hour <= end_hour for leg in flight.legs)
    ]


def filter_flights_by_airlines(flights: list, airlines: list[Airline]) -> list:
    """Filter flights by specified airlines."""
    return [flight for flight in flights if any(leg.airline in airlines for leg in flight.legs)]


def filter_dates_by_days(dates: list, days: list[DayOfWeek], trip_type: TripType) -> list:
    """Filter dates by days of the week."""
    if not days:
        return dates

    day_numbers = {
        DayOfWeek.MONDAY: 0,
        DayOfWeek.TUESDAY: 1,
        DayOfWeek.WEDNESDAY: 2,
        DayOfWeek.THURSDAY: 3,
        DayOfWeek.FRIDAY: 4,
        DayOfWeek.SATURDAY: 5,
        DayOfWeek.SUNDAY: 6,
    }

    allowed_days = {day_numbers[day] for day in days}
    return [date_price for date_price in dates if date_price.date[0].weekday() in allowed_days]


def format_airport(airport: Airport) -> str:
    """Format airport code and name (first two words)."""
    name_parts = airport.value.split()[:3]  # Get first three words
    name = " ".join(name_parts)
    return f"{airport.name} ({name})"


def format_duration(minutes: int) -> str:
    """Format duration in minutes to hours and minutes."""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def serialize_airport(airport: Airport) -> dict[str, str]:
    """Serialize an airport for machine-readable output."""
    return {"code": airport.name, "name": airport.value}


def serialize_airline(airline: Airline) -> dict[str, str]:
    """Serialize an airline for machine-readable output."""
    return {"code": airline.name.lstrip("_"), "name": airline.value}


def serialize_flight_leg(leg: Any) -> dict[str, Any]:
    """Serialize a flight leg using Google Flights-style field names."""
    return {
        "departure_airport": serialize_airport(leg.departure_airport),
        "arrival_airport": serialize_airport(leg.arrival_airport),
        "departure_time": leg.departure_datetime.isoformat(),
        "arrival_time": leg.arrival_datetime.isoformat(),
        "duration": leg.duration,
        "airline": serialize_airline(leg.airline),
        "flight_number": leg.flight_number,
    }


def _serialize_flight_segment_result(flight: Any, *, include_price: bool = False) -> dict[str, Any]:
    """Serialize a one-direction flight result."""
    payload = {
        "duration": flight.duration,
        "stops": flight.stops,
        "legs": [serialize_flight_leg(leg) for leg in flight.legs],
    }
    if include_price:
        payload["price"] = flight.price
        payload["currency"] = flight.currency or DEFAULT_CURRENCY
    return payload


def serialize_flight_result(flight_data: Any) -> dict[str, Any]:
    """Serialize a flight result or round-trip/multi-city tuple for JSON output."""
    if not isinstance(flight_data, tuple):
        return _serialize_flight_segment_result(flight_data, include_price=True)

    segments = list(flight_data)

    if len(segments) == 2:
        # Round-trip: Google Flights returns the full RT price on the outbound leg.
        outbound, return_flight = segments
        return {
            "price": outbound.price,
            "currency": outbound.currency or DEFAULT_CURRENCY,
            "duration": outbound.duration + return_flight.duration,
            "stops": outbound.stops + return_flight.stops,
            "outbound": _serialize_flight_segment_result(outbound),
            "return": _serialize_flight_segment_result(return_flight),
        }

    # Multi-city (3+ legs): combined price is on the final leg.
    price_segment = segments[-1]
    return {
        "price": price_segment.price,
        "currency": price_segment.currency or DEFAULT_CURRENCY,
        "duration": sum(s.duration for s in segments),
        "stops": sum(s.stops for s in segments),
        "segments": [_serialize_flight_segment_result(s) for s in segments],
    }


def serialize_date_result(date_result: Any, trip_type: TripType) -> dict[str, Any]:
    """Serialize a date search result for JSON output."""
    payload = {
        "departure_date": date_result.date[0].date().isoformat(),
        "return_date": None,
        "price": date_result.price,
        "currency": date_result.currency or DEFAULT_CURRENCY,
    }
    if trip_type == TripType.ROUND_TRIP and len(date_result.date) > 1:
        payload["return_date"] = date_result.date[1].date().isoformat()
    return payload


def build_json_success_response(
    *,
    search_type: str,
    trip_type: TripType,
    query: dict[str, Any],
    results_key: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a JSON success payload for CLI commands."""
    return {
        "success": True,
        "data_source": "google_flights",
        "search_type": search_type,
        "trip_type": trip_type.name,
        "query": query,
        "count": len(results),
        results_key: results,
    }


def build_json_error_response(
    *,
    search_type: str,
    message: str,
    error_type: str = "validation_error",
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON error payload for CLI commands."""
    payload = {
        "success": False,
        "data_source": "google_flights",
        "search_type": search_type,
        "error": {
            "type": error_type,
            "message": message,
        },
    }
    if query is not None:
        payload["query"] = query
    return payload


def emit_json(payload: dict[str, Any]) -> None:
    """Emit a JSON payload to stdout."""
    typer.echo(json.dumps(payload, indent=2))


def display_flight_results(flights: list):
    """Display flight results in a beautiful format.

    Args:
        flights: List of either FlightResult objects (one-way)
        or tuples of (outbound, return) FlightResults (round-trip)

    """
    if not flights:
        console.print(Panel("No flights found matching your criteria", style="red"))
        return

    for i, flight_data in enumerate(flights, 1):
        is_multi_leg = isinstance(flight_data, tuple)
        flight_segments = list(flight_data) if is_multi_leg else [flight_data]
        num_legs = len(flight_segments)

        # Create main flight info table
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("Label", style="blue")
        table.add_column("Value", style="green")

        # Google Flights returns the full trip price on the outbound leg for round-trips,
        # and on the final leg for multi-city trips.
        price_segment = flight_segments[-1] if num_legs > 2 else flight_segments[0]
        total_price = price_segment.price
        table.add_row("Total Price", format_price(total_price, price_segment.currency))

        total_duration = sum(flight.duration for flight in flight_segments)
        table.add_row("Total Duration", format_duration(total_duration))
        total_stops = sum(flight.stops for flight in flight_segments)
        table.add_row("Total Stops", str(total_stops))

        # Create segments tables for each direction
        all_segments = []
        for idx, flight in enumerate(flight_segments):
            if num_legs == 1:
                direction = ""
            elif num_legs == 2:
                direction = "Outbound" if idx == 0 else "Return"
            else:
                direction = f"Leg {idx + 1}"
            segments = Table(
                title=(f"{direction} Flight Segments" if direction else "Flight Segments"),
                box=box.ROUNDED,
            )
            segments.add_column("Flight", style="cyan", no_wrap=True)
            segments.add_column("From", style="yellow")
            segments.add_column("Depart", style="green", no_wrap=True)
            segments.add_column("To", style="yellow")
            segments.add_column("Arrive", style="green", no_wrap=True)

            for leg in flight.legs:
                airline_flight = f"{leg.airline.name.lstrip('_')} {leg.flight_number}"
                segments.add_row(
                    airline_flight,
                    format_airport(leg.departure_airport),
                    leg.departure_datetime.strftime("%H:%M %d-%b"),
                    format_airport(leg.arrival_airport),
                    leg.arrival_datetime.strftime("%H:%M %d-%b"),
                )
            all_segments.extend([segments, Text("")])

        # Display in a panel
        if num_legs > 2:
            title = "Multi-city Flight"
        elif num_legs == 2:
            title = "Round-trip Flight"
        else:
            title = "One-way Flight"
        console.print(
            Panel(
                Group(
                    Text(f"{title} Option {i}", style="bold blue"),
                    Text(""),
                    table,
                    Text(""),
                    *all_segments[:-1],  # Remove the last empty Text
                ),
                title=f"[bold]Option {i} of {len(flights)}[/bold]",
                border_style="blue",
                box=box.ROUNDED,
            )
        )
        console.print()


def display_date_results(dates: list, trip_type: TripType):
    """Display date search results with sparkline chart and table."""
    if not dates:
        console.print(Panel("No flights found for these dates", style="red"))
        return

    # Sort dates chronologically for proper trend visualization
    sorted_dates = sorted(dates, key=lambda x: x.date[0])

    # Extract data for chart
    date_labels = [d.date[0].strftime("%m/%d") for d in sorted_dates]
    prices = [d.price for d in sorted_dates]

    # Render sparkline chart
    plt.clear_figure()
    plt.plot(prices, marker="braille")
    plt.title("Price Trend")
    plt.xlabel("Date")
    plt.ylabel(format_price_axis_label(date.currency for date in sorted_dates))

    # Set x-axis labels (show subset if too many dates)
    if len(date_labels) <= 10:
        plt.xticks(range(len(date_labels)), date_labels)
    else:
        # Show every nth label to avoid crowding
        step = len(date_labels) // 8
        indices = list(range(0, len(date_labels), step))
        plt.xticks(indices, [date_labels[i] for i in indices])

    plt.theme("pro")
    plt.plotsize(80, 12)
    plt.show()

    console.print()  # Add spacing between chart and table

    # Build the table (using original order, not sorted)
    table = Table(title="Cheapest Dates to Fly", box=box.ROUNDED)
    table.add_column("Departure", style="cyan")
    table.add_column("Day", style="yellow")
    if trip_type == TripType.ROUND_TRIP:
        table.add_column("Return", style="cyan")
        table.add_column("Day", style="yellow")
    table.add_column("Price", style="green")

    for date_price in dates:
        if trip_type == TripType.ONE_WAY:
            table.add_row(
                date_price.date[0].strftime("%Y-%m-%d"),
                date_price.date[0].strftime("%A"),
                format_price(date_price.price, date_price.currency),
            )
        else:
            table.add_row(
                date_price.date[0].strftime("%Y-%m-%d"),
                date_price.date[0].strftime("%A"),
                date_price.date[1].strftime("%Y-%m-%d"),
                date_price.date[1].strftime("%A"),
                format_price(date_price.price, date_price.currency),
            )

    console.print(table)
    console.print()
