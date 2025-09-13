import os
from datetime import datetime, timedelta
from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from fli.models import (
    Airline,
    Airport,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
    TimeRestrictions,
    TripType,
)
from fli.search import SearchDates, SearchFlights


class FlightSearchRequest(BaseModel):
    """Search for flights between two airports on a specific date."""

    from_airport: str = Field(description="Departure airport code (e.g., 'JFK')")
    to_airport: str = Field(description="Arrival airport code (e.g., 'LHR')")
    date: str = Field(description="Travel date in YYYY-MM-DD format")
    return_date: str | None = Field(
        None, description="Return date in YYYY-MM-DD format for round trips"
    )
    time_range: str | None = Field(
        None, description="Time range in 24h format (e.g., '6-20')"
    )
    airlines: list[str] | None = Field(
        None, description="List of airline codes (e.g., ['BA', 'KL'])"
    )
    seat_class: str = Field(
        "ECONOMY", description="Seat type: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST"
    )
    stops: str = Field(
        "ANY", description="Maximum stops: ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS"
    )
    sort_by: str = Field(
        "CHEAPEST",
        description="Sort by: CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME",
    )


class CheapFlightSearchRequest(BaseModel):
    """Search for the cheapest flights between two airports over a date range."""

    from_airport: str = Field(description="Departure airport code (e.g., 'JFK')")
    to_airport: str = Field(description="Arrival airport code (e.g., 'LHR')")
    from_date: str = Field(
        description="Start date for search range in YYYY-MM-DD format"
    )
    to_date: str = Field(description="End date for search range in YYYY-MM-DD format")
    duration: int = Field(3, description="Duration of trip in days for round trips")
    round_trip: bool = Field(
        False, description="Whether to search for round-trip flights"
    )
    airlines: list[str] | None = Field(
        None, description="List of airline codes (e.g., ['BA', 'KL'])"
    )
    seat_class: str = Field(
        "ECONOMY", description="Seat type: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST"
    )
    stops: str = Field(
        "ANY", description="Maximum stops: ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS"
    )
    time_range: str | None = Field(
        None, description="Time range in 24h format (e.g., '6-20')"
    )
    sort_by_price: bool = Field(
        False, description="Sort results by price (lowest to highest)"
    )


mcp = FastMCP("Flight Search MCP Server")


def parse_stops(stops: str) -> MaxStops:
    """Parse stops parameter to MaxStops enum."""
    stops_map = {
        "ANY": MaxStops.ANY,
        "NON_STOP": MaxStops.NON_STOP,
        "ONE_STOP": MaxStops.ONE_STOP_OR_FEWER,
        "TWO_PLUS_STOPS": MaxStops.TWO_OR_FEWER_STOPS,
    }
    if stops.upper() not in stops_map:
        raise ValueError(f"Invalid stops value: {stops}")
    return stops_map[stops.upper()]


def parse_time_range(time_range: str) -> tuple[int, int]:
    """Parse time range string to start and end hours."""
    start_str, end_str = time_range.split("-")
    return int(start_str), int(end_str)


def parse_airlines(airline_codes: list[str] | None) -> list[Airline] | None:
    """Convert airline code strings to Airline enum objects."""
    if not airline_codes:
        return None

    airlines = []
    for code in airline_codes:
        try:
            # The airline code is the enum name, not the value
            airline = getattr(Airline, code.upper())
            airlines.append(airline)
        except AttributeError as e:
            raise ValueError(f"Invalid airline code: {code}") from e

    return airlines if airlines else None


@mcp.tool()
def search_flights(request: FlightSearchRequest) -> dict[str, Any]:
    """Search for flights with flexible filtering options.

    This tool searches for flights between two airports on a specific date
    with various filtering options like time ranges, airlines, seat class, etc.
    """
    try:
        # Parse airports
        departure_airport = getattr(Airport, request.from_airport.upper())
        arrival_airport = getattr(Airport, request.to_airport.upper())

        # Parse seat type and sort options
        seat_type = getattr(SeatType, request.seat_class.upper())
        sort_by = getattr(SortBy, request.sort_by.upper())

        # Parse stops
        max_stops = parse_stops(request.stops)

        # Parse airlines
        airlines = parse_airlines(request.airlines)

        # Parse time restrictions
        time_restrictions = None
        if request.time_range:
            start_hour, end_hour = parse_time_range(request.time_range)
            time_restrictions = TimeRestrictions(
                earliest_departure=start_hour, latest_departure=end_hour
            )

        # Create flight segments
        flight_segments = [
            FlightSegment(
                departure_airport=[[departure_airport, 0]],
                arrival_airport=[[arrival_airport, 0]],
                travel_date=request.date,
                time_restrictions=time_restrictions,
            )
        ]

        # Add return segment if round trip
        trip_type = TripType.ONE_WAY
        if request.return_date:
            trip_type = TripType.ROUND_TRIP
            flight_segments.append(
                FlightSegment(
                    departure_airport=[[arrival_airport, 0]],
                    arrival_airport=[[departure_airport, 0]],
                    travel_date=request.return_date,
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
            return {"error": "No flights found", "flights": []}

        # Convert flights to serializable format
        flight_results = []
        for flight in flights:
            # Handle both single flights and round-trip tuples
            if isinstance(flight, tuple):
                # Round trip: tuple of (outbound, return) flights
                outbound, return_flight = flight
                flight_data = {
                    "price": outbound.price + return_flight.price,
                    "currency": "USD",  # Currently only USD is supported
                    "legs": [],
                }

                # Add outbound legs
                for leg in outbound.legs:
                    leg_data = {
                        "departure_airport": leg.departure_airport,
                        "arrival_airport": leg.arrival_airport,
                        "departure_time": leg.departure_datetime,
                        "arrival_time": leg.arrival_datetime,
                        "duration": leg.duration,
                        "airline": leg.airline,
                        "flight_number": leg.flight_number,
                    }
                    flight_data["legs"].append(leg_data)

                # Add return legs
                for leg in return_flight.legs:
                    leg_data = {
                        "departure_airport": leg.departure_airport,
                        "arrival_airport": leg.arrival_airport,
                        "departure_time": leg.departure_datetime,
                        "arrival_time": leg.arrival_datetime,
                        "duration": leg.duration,
                        "airline": leg.airline,
                        "flight_number": leg.flight_number,
                    }
                    flight_data["legs"].append(leg_data)
            else:
                # One way flight
                flight_data = {
                    "price": flight.price,
                    "currency": "USD",  # Currently only USD is supported
                    "legs": [],
                }

                for leg in flight.legs:
                    leg_data = {
                        "departure_airport": leg.departure_airport,
                        "arrival_airport": leg.arrival_airport,
                        "departure_time": leg.departure_datetime,
                        "arrival_time": leg.arrival_datetime,
                        "duration": leg.duration,
                        "airline": leg.airline,
                        "flight_number": leg.flight_number,
                    }
                    flight_data["legs"].append(leg_data)

            flight_results.append(flight_data)

        return {
            "success": True,
            "flights": flight_results,
            "count": len(flight_results),
            "trip_type": trip_type.name,
        }

    except Exception as e:
        error_msg = str(e)
        if "Invalid airline code" in error_msg:
            return {"success": False, "error": "Invalid airline code", "flights": []}
        elif "Invalid stops value" in error_msg:
            return {"success": False, "error": "Invalid parameter value", "flights": []}
        elif "has no attribute" in error_msg and (
            "Airport" in error_msg or "SeatType" in error_msg
        ):
            return {"success": False, "error": "Invalid parameter value", "flights": []}
        elif (
            "Invalid time range" in error_msg
            or "split" in error_msg
            or "invalid literal for int()" in error_msg
        ):
            return {
                "success": False,
                "error": "Invalid time range format",
                "flights": [],
            }
        elif "validation error" in error_msg and (
            "Airport" in error_msg or "airline" in error_msg.lower()
        ):
            return {"success": False, "error": "Invalid parameter value", "flights": []}
        else:
            return {
                "success": False,
                "error": f"Search failed: {error_msg}",
                "flights": [],
            }


@mcp.tool()
def search_cheap_flights(request: CheapFlightSearchRequest) -> dict[str, Any]:
    """Find the cheapest dates to fly between two airports over a date range.

    This tool searches for the cheapest flights across a flexible date range,
    perfect for finding the best deals when your travel dates are flexible.
    """
    try:
        # Parse airports
        departure_airport = getattr(Airport, request.from_airport.upper())
        arrival_airport = getattr(Airport, request.to_airport.upper())

        # Parse options
        trip_type = TripType.ROUND_TRIP if request.round_trip else TripType.ONE_WAY
        seat_type = getattr(SeatType, request.seat_class.upper())
        max_stops = parse_stops(request.stops)
        airlines = parse_airlines(request.airlines)

        # Parse time restrictions
        time_restrictions = None
        if request.time_range:
            start_hour, end_hour = parse_time_range(request.time_range)
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
            travel_date=request.from_date,
            time_restrictions=time_restrictions,
        )

        # Handle round trip
        flight_segments = [flight_segment]
        if trip_type == TripType.ROUND_TRIP:
            return_flight_segment = FlightSegment(
                departure_airport=[[arrival_airport, 0]],
                arrival_airport=[[departure_airport, 0]],
                travel_date=(
                    datetime.strptime(flight_segment.travel_date, "%Y-%m-%d")
                    + timedelta(days=request.duration)
                ).strftime("%Y-%m-%d"),
                time_restrictions=time_restrictions,
            )
            flight_segments.append(return_flight_segment)

        # Create search filters
        filters = DateSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=flight_segments,
            stops=max_stops,
            seat_type=seat_type,
            airlines=airlines,
            from_date=request.from_date,
            to_date=request.to_date,
            duration=request.duration if trip_type == TripType.ROUND_TRIP else None,
        )

        # Perform search
        search_client = SearchDates()
        dates = search_client.search(filters)

        if not dates:
            return {"error": "No flights found for these dates", "dates": []}

        # Sort by price if requested
        if request.sort_by_price:
            dates.sort(key=lambda x: x.price)

        # Convert dates to serializable format
        date_results = []
        for date_result in dates:
            date_data = {
                "date": date_result.date,
                "price": date_result.price,
                "currency": "USD",  # Currently only USD is supported
                "return_date": getattr(date_result, "return_date", None),
            }
            date_results.append(date_data)

        return {
            "success": True,
            "dates": date_results,
            "count": len(date_results),
            "trip_type": trip_type.name,
            "date_range": f"{request.from_date} to {request.to_date}",
            "duration": request.duration if trip_type == TripType.ROUND_TRIP else None,
        }

    except Exception as e:
        return {"error": f"Date search failed: {str(e)}", "dates": []}


def run():
    """Run the MCP server on STDIO."""
    mcp.run(transport="stdio")


def run_http(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the MCP server over HTTP (streamable).

    Args:
        host: Host interface to bind the HTTP server.
        port: Port to listen on.

    """
    env_host = os.getenv("HOST")
    env_port = os.getenv("PORT")

    bind_host = env_host if env_host else host
    bind_port = int(env_port) if env_port else port

    mcp.run(transport="http", host=bind_host, port=bind_port)


if __name__ == "__main__":
    run()
