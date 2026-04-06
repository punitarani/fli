"""Flight Search MCP Server.

This module provides an MCP (Model Context Protocol) server for flight search
functionality, enabling AI assistants to search for flights and find cheapest
travel dates.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from fli.core import (
    build_date_search_segments,
    build_flight_segments,
    build_time_restrictions,
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
    DateSearchFilters,
    FlightSearchFilters,
    PassengerInfo,
    TripType,
)
from fli.search import SearchDates, SearchFlights


class FlightSearchConfig(BaseSettings):
    """Optional configuration for the Flight Search MCP server."""

    model_config = SettingsConfigDict(env_prefix="FLI_MCP_")

    default_passengers: int = Field(
        1,
        ge=1,
        description="Default number of adult passengers to include in searches.",
    )
    default_currency: str = Field(
        "USD",
        min_length=3,
        max_length=3,
        description="Fallback currency code when Google does not expose one in results.",
    )
    default_cabin_class: str = Field(
        "ECONOMY",
        description="Default cabin class used when none is provided.",
    )
    default_sort_by: str = Field(
        "CHEAPEST",
        description="Default sorting strategy for flight results.",
    )
    default_departure_window: str | None = Field(
        None,
        description="Optional default departure window in 'HH-HH' 24-hour format.",
    )
    max_results: int | None = Field(
        None,
        gt=0,
        description="Optional maximum number of results returned by each tool.",
    )


CONFIG = FlightSearchConfig()
CONFIG_SCHEMA = FlightSearchConfig.model_json_schema()


mcp = FastMCP("Flight Search MCP Server")


# =============================================================================
# Request/Response Models
# =============================================================================


class FlightSearchParams(BaseModel):
    """Parameters for searching flights on a specific date."""

    origin: str = Field(description="Departure airport IATA code (e.g., 'JFK', 'LAX')")
    destination: str = Field(description="Arrival airport IATA code (e.g., 'LHR', 'NRT')")
    departure_date: str = Field(description="Outbound travel date in YYYY-MM-DD format")
    return_date: str | None = Field(
        None, description="Return date in YYYY-MM-DD format (omit for one-way)"
    )
    departure_window: str | None = Field(
        None, description="Preferred departure time window in 'HH-HH' 24h format (e.g., '6-20')"
    )
    airlines: list[str] | None = Field(
        None, description="Filter by airline IATA codes (e.g., ['BA', 'AA'])"
    )
    cabin_class: str = Field(
        CONFIG.default_cabin_class,
        description="Cabin class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, or FIRST",
    )
    max_stops: str = Field(
        "ANY", description="Maximum stops: ANY, NON_STOP, ONE_STOP, or TWO_PLUS_STOPS"
    )
    sort_by: str = Field(
        CONFIG.default_sort_by,
        description="Sort results by: CHEAPEST, DURATION, DEPARTURE_TIME, or ARRIVAL_TIME",
    )
    passengers: int = Field(
        CONFIG.default_passengers,
        ge=1,
        description="Number of adult passengers",
    )
    exclude_basic_economy: bool = Field(
        False, description="Exclude basic economy fares from results"
    )
    emissions: str = Field("ALL", description="Filter by emissions level: ALL or LESS")
    checked_bags: int = Field(
        0, ge=0, le=2, description="Number of checked bags to include in price (0, 1, or 2)"
    )
    carry_on: bool = Field(False, description="Include carry-on bag fee in displayed price")
    show_all_results: bool = Field(
        True, description="Return all available results instead of curated ~30"
    )


class DateSearchParams(BaseModel):
    """Parameters for finding the cheapest travel dates within a range."""

    origin: str = Field(description="Departure airport IATA code (e.g., 'JFK', 'LAX')")
    destination: str = Field(description="Arrival airport IATA code (e.g., 'LHR', 'NRT')")
    start_date: str = Field(description="Start of date range in YYYY-MM-DD format")
    end_date: str = Field(description="End of date range in YYYY-MM-DD format")
    trip_duration: int = Field(
        3, ge=1, description="Trip duration in days (for round-trip searches)"
    )
    is_round_trip: bool = Field(False, description="Search for round-trip flights")
    airlines: list[str] | None = Field(
        None, description="Filter by airline IATA codes (e.g., ['BA', 'AA'])"
    )
    cabin_class: str = Field(
        CONFIG.default_cabin_class,
        description="Cabin class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, or FIRST",
    )
    max_stops: str = Field(
        "ANY", description="Maximum stops: ANY, NON_STOP, ONE_STOP, or TWO_PLUS_STOPS"
    )
    departure_window: str | None = Field(
        None, description="Preferred departure time window in 'HH-HH' 24h format (e.g., '6-20')"
    )
    sort_by_price: bool = Field(False, description="Sort results by price (lowest first)")
    passengers: int = Field(
        CONFIG.default_passengers,
        ge=1,
        description="Number of adult passengers",
    )


# =============================================================================
# Result Serialization
# =============================================================================


def _serialize_flight_leg(leg: Any) -> dict[str, Any]:
    """Serialize a single flight leg to a dictionary."""
    return {
        "departure_airport": leg.departure_airport,
        "arrival_airport": leg.arrival_airport,
        "departure_time": leg.departure_datetime,
        "arrival_time": leg.arrival_datetime,
        "duration": leg.duration,
        "airline": leg.airline,
        "airline_code": getattr(leg.airline, "name", leg.airline).lstrip("_"),
        "flight_number": leg.flight_number,
    }


def _serialize_flight_result(flight: Any, is_round_trip: bool = False) -> dict[str, Any]:
    """Serialize a flight result (or round-trip/multi-city tuple) to a dictionary."""
    if not isinstance(flight, tuple):
        return {
            "price": flight.price,
            "currency": flight.currency or CONFIG.default_currency,
            "legs": [_serialize_flight_leg(leg) for leg in flight.legs],
        }

    segments = list(flight)

    if len(segments) == 2 and is_round_trip:
        # Google Flights returns the full round-trip price on the outbound leg
        outbound, return_flight = segments
        return {
            "price": outbound.price,
            "currency": outbound.currency or CONFIG.default_currency,
            "legs": [
                *[_serialize_flight_leg(leg) for leg in outbound.legs],
                *[_serialize_flight_leg(leg) for leg in return_flight.legs],
            ],
        }

    # Multi-city (3+ legs) or 2-leg non-round-trip: combined price on the
    # final leg (matches Google Flights pricing and the CLI display logic).
    price_segment = segments[-1] if len(segments) > 2 else segments[0]
    return {
        "price": price_segment.price,
        "currency": price_segment.currency or CONFIG.default_currency,
        "legs": [_serialize_flight_leg(leg) for segment in segments for leg in segment.legs],
    }


def _serialize_date_result(date_result: Any) -> dict[str, Any]:
    """Serialize a date price result to a dictionary."""
    return {
        "date": date_result.date,
        "price": date_result.price,
        "currency": date_result.currency or CONFIG.default_currency,
        "return_date": getattr(date_result, "return_date", None),
    }


# =============================================================================
# Search Execution
# =============================================================================


def _execute_flight_search(params: FlightSearchParams) -> dict[str, Any]:
    """Execute a flight search and return formatted results."""
    try:
        # Parse inputs using shared utilities
        origin = resolve_airport(params.origin)
        destination = resolve_airport(params.destination)
        cabin_class = parse_cabin_class(params.cabin_class)
        max_stops = parse_max_stops(params.max_stops)
        sort_by = parse_sort_by(params.sort_by)
        airlines = parse_airlines(params.airlines)

        # Build time restrictions
        departure_window = params.departure_window or CONFIG.default_departure_window
        time_restrictions = build_time_restrictions(departure_window) if departure_window else None

        # Build flight segments
        segments, trip_type = build_flight_segments(
            origin=origin,
            destination=destination,
            departure_date=params.departure_date,
            return_date=params.return_date,
            time_restrictions=time_restrictions,
        )

        # Parse new filters
        emissions_filter = parse_emissions(params.emissions)
        bags_filter = None
        if params.checked_bags > 0 or params.carry_on:
            bags_filter = BagsFilter(checked_bags=params.checked_bags, carry_on=params.carry_on)

        # Create search filters
        filters = FlightSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=params.passengers),
            flight_segments=segments,
            stops=max_stops,
            seat_type=cabin_class,
            airlines=airlines,
            sort_by=sort_by,
            exclude_basic_economy=params.exclude_basic_economy,
            emissions=emissions_filter,
            bags=bags_filter,
            show_all_results=params.show_all_results,
        )

        # Perform search
        search_client = SearchFlights()
        flights = search_client.search(filters)

        if not flights:
            return {"success": True, "flights": [], "count": 0, "trip_type": trip_type.name}

        # Serialize results
        is_round_trip = trip_type == TripType.ROUND_TRIP
        flight_results = [_serialize_flight_result(f, is_round_trip) for f in flights]

        if CONFIG.max_results:
            flight_results = flight_results[: CONFIG.max_results]

        return {
            "success": True,
            "flights": flight_results,
            "count": len(flight_results),
            "trip_type": trip_type.name,
        }

    except ParseError as e:
        return {"success": False, "error": str(e), "flights": []}
    except Exception as e:
        error_msg = str(e)
        if "validation error" in error_msg.lower():
            return {"success": False, "error": "Invalid parameter value", "flights": []}
        return {"success": False, "error": f"Search failed: {error_msg}", "flights": []}


def _execute_date_search(params: DateSearchParams) -> dict[str, Any]:
    """Execute a date search and return formatted results."""
    try:
        # Parse inputs using shared utilities
        origin = resolve_airport(params.origin)
        destination = resolve_airport(params.destination)
        cabin_class = parse_cabin_class(params.cabin_class)
        max_stops = parse_max_stops(params.max_stops)
        airlines = parse_airlines(params.airlines)

        # Build time restrictions
        departure_window = params.departure_window or CONFIG.default_departure_window
        time_restrictions = build_time_restrictions(departure_window) if departure_window else None

        # Build flight segments
        segments, trip_type = build_date_search_segments(
            origin=origin,
            destination=destination,
            start_date=params.start_date,
            trip_duration=params.trip_duration,
            is_round_trip=params.is_round_trip,
            time_restrictions=time_restrictions,
        )

        # Create search filters
        filters = DateSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=params.passengers),
            flight_segments=segments,
            stops=max_stops,
            seat_type=cabin_class,
            airlines=airlines,
            from_date=params.start_date,
            to_date=params.end_date,
            duration=params.trip_duration if params.is_round_trip else None,
        )

        # Perform search
        search_client = SearchDates()
        dates = search_client.search(filters)

        if not dates:
            return {
                "success": True,
                "dates": [],
                "count": 0,
                "trip_type": trip_type.name,
                "date_range": f"{params.start_date} to {params.end_date}",
            }

        if params.sort_by_price:
            dates.sort(key=lambda x: x.price)

        # Serialize results
        date_results = [_serialize_date_result(d) for d in dates]

        if CONFIG.max_results:
            date_results = date_results[: CONFIG.max_results]

        return {
            "success": True,
            "dates": date_results,
            "count": len(date_results),
            "trip_type": trip_type.name,
            "date_range": f"{params.start_date} to {params.end_date}",
            "duration": params.trip_duration if params.is_round_trip else None,
        }

    except ParseError as e:
        return {"success": False, "error": str(e), "dates": []}
    except Exception as e:
        return {"success": False, "error": f"Search failed: {str(e)}", "dates": []}


# =============================================================================
# MCP Tools
# =============================================================================


@mcp.tool(
    annotations={
        "title": "Search Flights",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
def search_flights(
    origin: Annotated[str, Field(description="Departure airport IATA code (e.g., 'JFK')")],
    destination: Annotated[str, Field(description="Arrival airport IATA code (e.g., 'LHR')")],
    departure_date: Annotated[str, Field(description="Travel date in YYYY-MM-DD format")],
    return_date: Annotated[
        str | None,
        Field(description="Return date in YYYY-MM-DD format (omit for one-way)"),
    ] = None,
    departure_window: Annotated[
        str | None,
        Field(description="Departure time window in 'HH-HH' 24h format (e.g., '6-20')"),
    ] = None,
    airlines: Annotated[
        list[str] | None,
        Field(description="Filter by airline IATA codes (e.g., ['BA', 'AA'])"),
    ] = None,
    cabin_class: Annotated[
        str,
        Field(description="Cabin class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST"),
    ] = CONFIG.default_cabin_class,
    max_stops: Annotated[
        str,
        Field(description="Maximum stops: ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS"),
    ] = "ANY",
    sort_by: Annotated[
        str,
        Field(
            description="Sort by: TOP_FLIGHTS, BEST, CHEAPEST,"
            " DEPARTURE_TIME, ARRIVAL_TIME, DURATION, EMISSIONS"
        ),
    ] = CONFIG.default_sort_by,
    passengers: Annotated[
        int | None,
        Field(description="Number of adult passengers", ge=1),
    ] = None,
    exclude_basic_economy: Annotated[
        bool,
        Field(description="Exclude basic economy fares from results"),
    ] = False,
    emissions: Annotated[
        str,
        Field(description="Filter by emissions level: ALL or LESS"),
    ] = "ALL",
    checked_bags: Annotated[
        int,
        Field(description="Number of checked bags to include in price (0, 1, or 2)", ge=0, le=2),
    ] = 0,
    carry_on: Annotated[
        bool,
        Field(description="Include carry-on bag fee in displayed price"),
    ] = False,
    show_all_results: Annotated[
        bool,
        Field(description="Return all available results instead of curated ~30"),
    ] = True,
) -> dict[str, Any]:
    """Search for flights between two airports on a specific date.

    Returns a list of available flights with prices, durations, and leg details.
    Supports one-way and round-trip searches with various filtering options.
    """
    effective_departure_window = departure_window or CONFIG.default_departure_window
    params = FlightSearchParams(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        departure_window=effective_departure_window,
        airlines=airlines,
        cabin_class=cabin_class,
        max_stops=max_stops,
        sort_by=sort_by,
        passengers=passengers or CONFIG.default_passengers,
        exclude_basic_economy=exclude_basic_economy,
        emissions=emissions,
        checked_bags=checked_bags,
        carry_on=carry_on,
        show_all_results=show_all_results,
    )
    return _execute_flight_search(params)


def _search_flights_from_params(params: FlightSearchParams) -> dict[str, Any]:
    """Entry point for tests that call the tool via a params object."""
    return _execute_flight_search(params)


@mcp.tool(
    annotations={
        "title": "Search Dates",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
def search_dates(
    origin: Annotated[str, Field(description="Departure airport IATA code (e.g., 'JFK')")],
    destination: Annotated[str, Field(description="Arrival airport IATA code (e.g., 'LHR')")],
    start_date: Annotated[str, Field(description="Start of date range in YYYY-MM-DD format")],
    end_date: Annotated[str, Field(description="End of date range in YYYY-MM-DD format")],
    trip_duration: Annotated[
        int,
        Field(description="Trip duration in days for round-trips", ge=1),
    ] = 3,
    is_round_trip: Annotated[
        bool,
        Field(description="Search for round-trip flights"),
    ] = False,
    airlines: Annotated[
        list[str] | None,
        Field(description="Filter by airline IATA codes (e.g., ['BA', 'AA'])"),
    ] = None,
    cabin_class: Annotated[
        str,
        Field(description="Cabin class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST"),
    ] = CONFIG.default_cabin_class,
    max_stops: Annotated[
        str,
        Field(description="Maximum stops: ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS"),
    ] = "ANY",
    departure_window: Annotated[
        str | None,
        Field(description="Departure time window in 'HH-HH' 24h format (e.g., '6-20')"),
    ] = None,
    sort_by_price: Annotated[
        bool,
        Field(description="Sort results by price (lowest first)"),
    ] = False,
    passengers: Annotated[
        int | None,
        Field(description="Number of adult passengers", ge=1),
    ] = None,
) -> dict[str, Any]:
    """Find the cheapest travel dates between two airports within a date range.

    Returns a list of dates with their prices, useful for flexible travel planning.
    Supports both one-way and round-trip searches.
    """
    effective_departure_window = departure_window or CONFIG.default_departure_window
    params = DateSearchParams(
        origin=origin,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        trip_duration=trip_duration,
        is_round_trip=is_round_trip,
        airlines=airlines,
        cabin_class=cabin_class,
        max_stops=max_stops,
        departure_window=effective_departure_window,
        sort_by_price=sort_by_price,
        passengers=passengers or CONFIG.default_passengers,
    )
    return _execute_date_search(params)


def _search_dates_from_params(params: DateSearchParams) -> dict[str, Any]:
    """Entry point for tests that call the tool via a params object."""
    return _execute_date_search(params)


# =============================================================================
# Prompts
# =============================================================================


@mcp.prompt(
    name="search-direct-flight",
    description=(
        "Generate a tool call to find direct flights between two airports on a target date."
    ),
)
def search_direct_flight_prompt(
    origin: str,
    destination: str,
    date: str | None = None,
    prefer_non_stop: bool = True,
) -> str:
    """Create a helper prompt to guide flight searches."""
    travel_date = date or datetime.now(timezone.utc).date().isoformat()
    max_stops_hint = "NON_STOP" if prefer_non_stop else "ANY"
    return (
        "Use the `search_flights` tool to look for flights from "
        f"{origin.upper()} to {destination.upper()} departing on {travel_date}. "
        f"Set `max_stops` to '{max_stops_hint}' and highlight the three most affordable options."
    )


@mcp.prompt(
    name="find-budget-window",
    description="Suggest the cheapest travel dates for a route within a flexible window.",
)
def find_budget_window_prompt(
    origin: str,
    destination: str,
    start_date: str | None = None,
    end_date: str | None = None,
    duration: int = 7,
) -> str:
    """Create a helper prompt to guide flexible date searches."""
    today = datetime.now(timezone.utc).date()
    travel_start = start_date or (today + timedelta(days=30)).isoformat()
    travel_end = end_date or (today + timedelta(days=90)).isoformat()
    return (
        "Use the `search_dates` tool to find the lowest fares between "
        f"{origin.upper()} and {destination.upper()} for trips between "
        f"{travel_start} and {travel_end}. "
        f"Set trip_duration to {duration} days and sort the results by price."
    )


# =============================================================================
# Resources
# =============================================================================


@mcp.resource(
    "resource://fli-mcp/configuration",
    name="Fli MCP Configuration",
    description=(
        "Optional configuration defaults and environment variables for the Flight "
        "Search MCP server."
    ),
    mime_type="application/json",
)
def configuration_resource() -> str:
    """Expose configuration defaults and schema as a resource."""
    payload = {
        "defaults": CONFIG.model_dump(),
        "schema": CONFIG_SCHEMA,
        "environment": {
            "prefix": "FLI_MCP_",
            "variables": {
                "FLI_MCP_DEFAULT_PASSENGERS": "Adjust the default passenger count.",
                "FLI_MCP_DEFAULT_CURRENCY": "Override the fallback currency code for results.",
                "FLI_MCP_DEFAULT_CABIN_CLASS": "Set a default cabin class.",
                "FLI_MCP_DEFAULT_SORT_BY": "Set the default result sorting strategy.",
                "FLI_MCP_DEFAULT_DEPARTURE_WINDOW": "Provide a default departure window (HH-HH).",
                "FLI_MCP_MAX_RESULTS": "Limit the maximum number of results returned by tools.",
            },
        },
    }
    return json.dumps(payload, indent=2)


# =============================================================================
# Entry Points
# =============================================================================


def run():
    """Run the MCP server on STDIO."""
    mcp.run(transport="stdio")


def run_http(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the MCP server over HTTP (streamable)."""
    env_host = os.getenv("HOST")
    env_port = os.getenv("PORT")

    bind_host = env_host if env_host else host
    bind_port = int(env_port) if env_port else port

    mcp.run(transport="http", host=bind_host, port=bind_port)


if __name__ == "__main__":
    run()
