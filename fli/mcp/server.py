import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools import Tool as FastMCPTool
from mcp.types import (
    GetPromptResult,
    ListPromptsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Role,
    TextContent,
    Tool,
    ToolAnnotations,
)
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

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
        description="Three-letter currency code returned with search results.",
    )
    default_seat_class: str = Field(
        "ECONOMY",
        description="Default cabin class used when none is provided.",
    )
    default_sort_by: str = Field(
        "CHEAPEST",
        description="Default sorting strategy for flight results.",
    )
    default_time_range: str | None = Field(
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


@dataclass
class PromptSpec:
    """Container for prompt metadata and builder."""

    description: str
    build_messages: Callable[[dict[str, str]], list[PromptMessage]]
    arguments: list[PromptArgument] | None = None


class FliMCP(FastMCP):
    """Extended FastMCP server with prompt and annotation support."""

    def __init__(self, name: str | None = None, **settings: Any):
        """Initialize the MCP server with metadata tracking for tools and prompts."""
        self._tool_annotations: dict[str, ToolAnnotations] = {}
        self._prompts: dict[str, PromptSpec] = {}
        super().__init__(name=name, **settings)

    def _setup_handlers(self) -> None:
        """Register MCP protocol handlers including prompts."""
        super()._setup_handlers()  # Set up standard handlers from parent
        # Override only the handlers that FliMCP customizes
        self._mcp_server.list_tools()(self.list_tools)
        self._mcp_server.list_prompts()(self.list_prompts)
        self._mcp_server.get_prompt()(self.get_prompt)

    def add_tool(
        self,
        func: Callable,
        name: str | None = None,
        description: str | None = None,
        annotations: dict[str, Any] | ToolAnnotations | None = None,
    ) -> None:
        """Register a tool with optional annotations."""
        tool = FastMCPTool.from_function(fn=func, name=name, description=description)
        self._tool_manager.add_tool(tool)
        tool_name = name or func.__name__
        if annotations:
            self._tool_annotations[tool_name] = (
                annotations
                if isinstance(annotations, ToolAnnotations)
                else ToolAnnotations(**annotations)
            )

    def tool(
        self,
        name: str | None = None,
        description: str | None = None,
        annotations: dict[str, Any] | ToolAnnotations | None = None,
    ) -> Callable:
        """Register a tool with optional annotations."""
        if callable(name):
            raise TypeError(
                "The @tool decorator was used incorrectly. "
                "Did you forget to call it? Use @tool() instead of @tool"
            )

        def decorator(func: Callable) -> Callable:
            self.add_tool(func, name=name, description=description, annotations=annotations)
            return func

        return decorator

    async def list_tools(self) -> list[Tool]:
        """List all available tools with annotations."""
        tools = self._tool_manager.list_tools()
        return [
            Tool(
                name=info.name,
                description=info.description,
                inputSchema=info.parameters,
                annotations=self._tool_annotations.get(info.name),
            )
            for info in tools
        ]

    def add_prompt(
        self,
        name: str,
        description: str,
        *,
        arguments: list[PromptArgument] | None = None,
        build_messages: Callable[[dict[str, str]], list[PromptMessage]],
    ) -> None:
        """Register a prompt template that can be listed and fetched."""
        self._prompts[name] = PromptSpec(
            description=description,
            arguments=arguments,
            build_messages=build_messages,
        )

    async def list_prompts(self) -> ListPromptsResult:
        """Return all registered prompts."""
        prompts = [
            Prompt(
                name=name,
                description=spec.description,
                arguments=spec.arguments,
            )
            for name, spec in self._prompts.items()
        ]
        return ListPromptsResult(prompts=prompts)

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
    ) -> GetPromptResult:
        """Generate prompt content by name."""
        spec = self._prompts.get(name)
        if not spec:
            raise ValueError(f"Unknown prompt: {name}")
        messages = spec.build_messages(arguments or {})
        return GetPromptResult(description=spec.description, messages=messages)


mcp = FliMCP("Flight Search MCP Server")


class FlightSearchRequest(BaseModel):
    """Search for flights between two airports on a specific date."""

    from_airport: str = Field(description="Departure airport code (e.g., 'JFK')")
    to_airport: str = Field(description="Arrival airport code (e.g., 'LHR')")
    date: str = Field(description="Travel date in YYYY-MM-DD format")
    return_date: str | None = Field(
        None, description="Return date in YYYY-MM-DD format for round trips"
    )
    time_range: str | None = Field(None, description="Time range in 24h format (e.g., '6-20')")
    airlines: list[str] | None = Field(
        None, description="List of airline codes (e.g., ['BA', 'KL'])"
    )
    seat_class: str = Field(
        CONFIG.default_seat_class,
        description="Seat type: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST",
    )
    stops: str = Field("ANY", description="Maximum stops: ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS")
    sort_by: str = Field(
        CONFIG.default_sort_by,
        description="Sort by: CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME",
    )
    passengers: int = Field(
        CONFIG.default_passengers,
        ge=1,
        description="Number of adult passengers to include in the search.",
    )


class CheapFlightSearchRequest(BaseModel):
    """Search for the cheapest flights between two airports over a date range."""

    from_airport: str = Field(description="Departure airport code (e.g., 'JFK')")
    to_airport: str = Field(description="Arrival airport code (e.g., 'LHR')")
    from_date: str = Field(description="Start date for search range in YYYY-MM-DD format")
    to_date: str = Field(description="End date for search range in YYYY-MM-DD format")
    duration: int = Field(3, description="Duration of trip in days for round trips")
    round_trip: bool = Field(False, description="Whether to search for round-trip flights")
    airlines: list[str] | None = Field(
        None, description="List of airline codes (e.g., ['BA', 'KL'])"
    )
    seat_class: str = Field(
        CONFIG.default_seat_class,
        description="Seat type: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST",
    )
    stops: str = Field("ANY", description="Maximum stops: ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS")
    time_range: str | None = Field(None, description="Time range in 24h format (e.g., '6-20')")
    sort_by_price: bool = Field(False, description="Sort results by price (lowest to highest)")
    passengers: int = Field(
        CONFIG.default_passengers,
        ge=1,
        description="Number of adult passengers to include when evaluating prices.",
    )


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
            airline = getattr(Airline, code.upper())
            airlines.append(airline)
        except AttributeError as e:
            raise ValueError(f"Invalid airline code: {code}") from e

    return airlines if airlines else None


def resolve_enum(enum_cls, name: str):
    """Resolve enum member name to enum value with normalized errors."""
    try:
        return getattr(enum_cls, name.upper())
    except AttributeError as e:
        raise ValueError("Invalid parameter value") from e


def _apply_flight_defaults(request: FlightSearchRequest) -> FlightSearchRequest:
    """Apply configuration defaults to a flight search request."""
    if request.passengers < 1:
        request.passengers = CONFIG.default_passengers
    if not request.seat_class:
        request.seat_class = CONFIG.default_seat_class
    if not request.sort_by:
        request.sort_by = CONFIG.default_sort_by
    if not request.time_range and CONFIG.default_time_range:
        request.time_range = CONFIG.default_time_range
    return request


def _execute_flight_search(request: FlightSearchRequest) -> dict[str, Any]:
    """Perform the flight search and format the results."""
    request = _apply_flight_defaults(request)
    try:
        # Parse airports
        departure_airport = resolve_enum(Airport, request.from_airport)
        arrival_airport = resolve_enum(Airport, request.to_airport)

        # Parse seat type and sort options
        seat_type = resolve_enum(SeatType, request.seat_class)
        sort_by = resolve_enum(SortBy, request.sort_by)

        # Parse stops
        max_stops = parse_stops(request.stops)

        # Parse airlines
        airlines = parse_airlines(request.airlines)

        # Parse time restrictions
        time_restrictions = None
        time_range = request.time_range or CONFIG.default_time_range
        if time_range:
            start_hour, end_hour = parse_time_range(time_range)
            time_restrictions = TimeRestrictions(
                earliest_departure=start_hour,
                latest_departure=end_hour,
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
            passenger_info=PassengerInfo(adults=request.passengers),
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
            if isinstance(flight, tuple):
                outbound, return_flight = flight
                flight_data = {
                    "price": outbound.price + return_flight.price,
                    "currency": CONFIG.default_currency,
                    "legs": [],
                }

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
                flight_data = {
                    "price": flight.price,
                    "currency": CONFIG.default_currency,
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

        if CONFIG.max_results:
            flight_results = flight_results[: CONFIG.max_results]

        return {
            "success": True,
            "flights": flight_results,
            "count": len(flight_results),
            "trip_type": trip_type.name,
        }

    except ValueError as e:
        error_msg = str(e)
        if (
            "Invalid time range" in error_msg
            or "split" in error_msg
            or "invalid literal for int()" in error_msg
        ):
            return {
                "success": False,
                "error": "Invalid time range format",
                "flights": [],
            }
        if "Invalid airline code" in error_msg:
            return {"success": False, "error": "Invalid airline code", "flights": []}
        if "Invalid stops value" in error_msg:
            return {"success": False, "error": "Invalid parameter value", "flights": []}
        return {"success": False, "error": "Invalid parameter value", "flights": []}
    except Exception as e:
        error_msg = str(e)
        if (
            "Invalid time range" in error_msg
            or "split" in error_msg
            or "invalid literal for int()" in error_msg
        ):
            return {
                "success": False,
                "error": "Invalid time range format",
                "flights": [],
            }
        if "validation error" in error_msg and (
            "Airport" in error_msg or "airline" in error_msg.lower()
        ):
            return {"success": False, "error": "Invalid parameter value", "flights": []}
        return {
            "success": False,
            "error": f"Search failed: {error_msg}",
            "flights": [],
        }


def _apply_date_defaults(request: CheapFlightSearchRequest) -> CheapFlightSearchRequest:
    """Apply configuration defaults to a date search request."""
    if request.passengers < 1:
        request.passengers = CONFIG.default_passengers
    if not request.seat_class:
        request.seat_class = CONFIG.default_seat_class
    if not request.time_range and CONFIG.default_time_range:
        request.time_range = CONFIG.default_time_range
    return request


def _execute_cheap_flight_search(request: CheapFlightSearchRequest) -> dict[str, Any]:
    """Perform the date search and format the results."""
    request = _apply_date_defaults(request)
    try:
        departure_airport = resolve_enum(Airport, request.from_airport)
        arrival_airport = resolve_enum(Airport, request.to_airport)

        trip_type = TripType.ROUND_TRIP if request.round_trip else TripType.ONE_WAY
        seat_type = resolve_enum(SeatType, request.seat_class)
        max_stops = parse_stops(request.stops)
        airlines = parse_airlines(request.airlines)

        time_restrictions = None
        time_range = request.time_range or CONFIG.default_time_range
        if time_range:
            start_hour, end_hour = parse_time_range(time_range)
            time_restrictions = TimeRestrictions(
                earliest_departure=start_hour,
                latest_departure=end_hour,
                earliest_arrival=None,
                latest_arrival=None,
            )

        flight_segment = FlightSegment(
            departure_airport=[[departure_airport, 0]],
            arrival_airport=[[arrival_airport, 0]],
            travel_date=request.from_date,
            time_restrictions=time_restrictions,
        )

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

        filters = DateSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=request.passengers),
            flight_segments=flight_segments,
            stops=max_stops,
            seat_type=seat_type,
            airlines=airlines,
            from_date=request.from_date,
            to_date=request.to_date,
            duration=request.duration if trip_type == TripType.ROUND_TRIP else None,
        )

        search_client = SearchDates()
        dates = search_client.search(filters)

        if not dates:
            return {"error": "No flights found for these dates", "dates": []}

        if request.sort_by_price:
            dates.sort(key=lambda x: x.price)

        date_results = []
        for date_result in dates:
            date_data = {
                "date": date_result.date,
                "price": date_result.price,
                "currency": CONFIG.default_currency,
                "return_date": getattr(date_result, "return_date", None),
            }
            date_results.append(date_data)

        if CONFIG.max_results:
            date_results = date_results[: CONFIG.max_results]

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


@mcp.tool(
    annotations={
        "title": "Search Flights",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
def search_flights(
    from_airport: Annotated[str, Field(description="Departure airport code (e.g., 'JFK')")],
    to_airport: Annotated[str, Field(description="Arrival airport code (e.g., 'LHR')")],
    date: Annotated[str, Field(description="Travel date in YYYY-MM-DD format")],
    return_date: Annotated[
        str | None,
        Field(description="Return date in YYYY-MM-DD format for round trips"),
    ] = None,
    time_range: Annotated[
        str | None,
        Field(description="Preferred departure window in 'HH-HH' 24-hour format"),
    ] = None,
    airlines: Annotated[
        list[str] | None,
        Field(description="List of airline codes (e.g., ['BA', 'KL'])"),
    ] = None,
    seat_class: Annotated[
        str,
        Field(description="Seat type: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST"),
    ] = CONFIG.default_seat_class,
    stops: Annotated[
        str,
        Field(description="Maximum stops: ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS"),
    ] = "ANY",
    sort_by: Annotated[
        str,
        Field(description="Sort by: CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME"),
    ] = CONFIG.default_sort_by,
    passengers: Annotated[
        int | None,
        Field(description="Override the default number of adult passengers.", ge=1),
    ] = None,
) -> dict[str, Any]:
    """Search for flights with flexible filtering options."""
    effective_time_range = time_range or CONFIG.default_time_range
    request = FlightSearchRequest(
        from_airport=from_airport,
        to_airport=to_airport,
        date=date,
        return_date=return_date,
        time_range=effective_time_range,
        airlines=airlines,
        seat_class=seat_class,
        stops=stops,
        sort_by=sort_by,
        passengers=passengers or CONFIG.default_passengers,
    )
    return _execute_flight_search(request)


def _search_flights_from_request(request: FlightSearchRequest) -> dict[str, Any]:
    """Compatibility wrapper for tests expecting the original request-based signature."""
    return _execute_flight_search(request)


search_flights.fn = _search_flights_from_request  # type: ignore[attr-defined]


@mcp.tool(
    annotations={
        "title": "Find Cheapest Dates",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
def search_cheap_flights(
    from_airport: Annotated[str, Field(description="Departure airport code (e.g., 'JFK')")],
    to_airport: Annotated[str, Field(description="Arrival airport code (e.g., 'LHR')")],
    from_date: Annotated[
        str, Field(description="Start date for search range in YYYY-MM-DD format")
    ],
    to_date: Annotated[str, Field(description="End date for search range in YYYY-MM-DD format")],
    duration: Annotated[
        int,
        Field(description="Duration of trip in days for round trips", ge=1),
    ] = 3,
    round_trip: Annotated[
        bool,
        Field(description="Whether to search for round-trip flights"),
    ] = False,
    airlines: Annotated[
        list[str] | None,
        Field(description="List of airline codes (e.g., ['BA', 'KL'])"),
    ] = None,
    seat_class: Annotated[
        str,
        Field(description="Seat type: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST"),
    ] = CONFIG.default_seat_class,
    stops: Annotated[
        str,
        Field(description="Maximum stops: ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS"),
    ] = "ANY",
    time_range: Annotated[
        str | None,
        Field(description="Preferred departure window in 'HH-HH' 24-hour format"),
    ] = None,
    sort_by_price: Annotated[
        bool,
        Field(description="Sort the resulting dates by price (lowest to highest)"),
    ] = False,
    passengers: Annotated[
        int | None,
        Field(description="Override the default number of adult passengers.", ge=1),
    ] = None,
) -> dict[str, Any]:
    """Find the cheapest travel dates between two airports."""
    effective_time_range = time_range or CONFIG.default_time_range
    request = CheapFlightSearchRequest(
        from_airport=from_airport,
        to_airport=to_airport,
        from_date=from_date,
        to_date=to_date,
        duration=duration,
        round_trip=round_trip,
        airlines=airlines,
        seat_class=seat_class,
        stops=stops,
        time_range=effective_time_range,
        sort_by_price=sort_by_price,
        passengers=passengers or CONFIG.default_passengers,
    )
    return _execute_cheap_flight_search(request)


def _search_cheap_flights_from_request(
    request: CheapFlightSearchRequest,
) -> dict[str, Any]:
    """Compatibility wrapper for tests expecting the original request-based signature."""
    return _execute_cheap_flight_search(request)


search_cheap_flights.fn = _search_cheap_flights_from_request  # type: ignore[attr-defined]


def _build_search_prompt(args: dict[str, str]) -> list[PromptMessage]:
    """Create a helper prompt to guide flight searches."""
    from_airport = args.get("from_airport", "JFK").upper()
    to_airport = args.get("to_airport", "LHR").upper()
    date = args.get("date") or datetime.utcnow().date().isoformat()
    prefer_non_stop = args.get("prefer_non_stop", "true").lower()
    stops_hint = "NON_STOP" if prefer_non_stop in {"true", "1", "yes"} else "ANY"
    text = (
        "Use the `search_flights` tool to look for flights from "
        f"{from_airport} to {to_airport} departing on {date}. "
        f"Set `stops` to '{stops_hint}' and highlight the three most affordable options."
    )
    return [
        PromptMessage(role=Role.USER, content=TextContent(type="text", text=text)),
    ]


def _build_budget_prompt(args: dict[str, str]) -> list[PromptMessage]:
    """Create a helper prompt to guide flexible date searches."""
    from_airport = args.get("from_airport", "SFO").upper()
    to_airport = args.get("to_airport", "NRT").upper()
    from_date = args.get("from_date") or (datetime.utcnow().date() + timedelta(days=30)).isoformat()
    to_date = args.get("to_date") or (datetime.utcnow().date() + timedelta(days=90)).isoformat()
    duration = args.get("duration", "7")
    text = (
        "Use the `search_cheap_flights` tool to find the lowest fares between "
        f"{from_airport} and {to_airport} for trips between {from_date} and {to_date}. "
        f"Limit the duration to {duration} days and sort the results by price."
    )
    return [
        PromptMessage(role=Role.USER, content=TextContent(type="text", text=text)),
    ]


mcp.add_prompt(
    name="search-direct-flight",
    description=(
        "Generate a tool call to find direct flights between two airports on a target date."
    ),
    arguments=[
        PromptArgument(
            name="from_airport",
            description="Departure airport code",
            required=True,
        ),
        PromptArgument(
            name="to_airport",
            description="Arrival airport code",
            required=True,
        ),
        PromptArgument(
            name="date",
            description="Departure date (YYYY-MM-DD)",
            required=False,
        ),
        PromptArgument(
            name="prefer_non_stop",
            description="Set to true to prefer nonstop itineraries",
            required=False,
        ),
    ],
    build_messages=_build_search_prompt,
)

mcp.add_prompt(
    name="find-budget-window",
    description=("Suggest the cheapest travel dates for a route within a flexible window."),
    arguments=[
        PromptArgument(
            name="from_airport",
            description="Departure airport code",
            required=True,
        ),
        PromptArgument(
            name="to_airport",
            description="Arrival airport code",
            required=True,
        ),
        PromptArgument(
            name="from_date",
            description="Start of the travel window (YYYY-MM-DD)",
            required=False,
        ),
        PromptArgument(
            name="to_date",
            description="End of the travel window (YYYY-MM-DD)",
            required=False,
        ),
        PromptArgument(
            name="duration",
            description="Desired trip length in days",
            required=False,
        ),
    ],
    build_messages=_build_budget_prompt,
)


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
                "FLI_MCP_DEFAULT_CURRENCY": "Override the currency code returned with results.",
                "FLI_MCP_DEFAULT_SEAT_CLASS": "Set a default seat class.",
                "FLI_MCP_DEFAULT_SORT_BY": "Set the default result sorting strategy.",
                "FLI_MCP_DEFAULT_TIME_RANGE": "Provide a default departure window (HH-HH).",
                "FLI_MCP_MAX_RESULTS": "Limit the maximum number of results returned by tools.",
            },
        },
    }
    return json.dumps(payload, indent=2)


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
