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
from mcp.types import Icon
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from fli.core import (
    build_date_search_segments,
    build_flight_segments,
    build_time_restrictions,
    google_flights_url,
    parse_airlines,
    parse_alliances,
    parse_cabin_class,
    parse_currency,
    parse_emissions,
    parse_max_stops,
    parse_sort_by,
    resolve_airport,
    search_airports,
)
from fli.core.parsers import ParseError
from fli.models import (
    Airport,
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


mcp = FastMCP(
    "Flight Search MCP Server",
    icons=[
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMDAgMTAwIj48dGV4dCB5PSIuOWVtIiBmb250LXNpemU9IjkwIj7inIjvuI88L3RleHQ+PC9zdmc+",
            mimeType="image/svg+xml",
        )
    ],
)


# =============================================================================
# Request/Response Models
# =============================================================================


class FlightSearchParams(BaseModel):
    """Parameters for searching flights on a specific date."""

    origin: str = Field(
        description="Departure airport IATA code(s), comma-separated for multiple (e.g., 'JFK,LGA')"
    )
    destination: str = Field(
        description="Arrival airport IATA code(s), comma-separated for multiple (e.g., 'LHR,CDG')"
    )
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
    currency: str | None = Field(
        None,
        description=(
            "ISO 4217 currency code (e.g. 'USD', 'EUR', 'GBP') to bill prices in. "
            "When omitted, Google picks based on locale (usually USD)."
        ),
    )
    language: str | None = Field(
        None,
        description="Optional BCP-47 language code (e.g. 'en-GB') passed to Google as `hl`.",
    )
    country: str | None = Field(
        None,
        description=(
            "Optional ISO 3166-1 alpha-2 country code (e.g. 'GB') for Google's `gl` param."
        ),
    )
    exclude_airlines: list[str] | None = Field(
        None,
        description="Airline IATA codes to EXCLUDE from results (e.g. ['DL', 'B6']).",
    )
    alliance: list[str] | None = Field(
        None,
        description=("Restrict to one or more alliances: 'ONEWORLD', 'SKYTEAM', 'STAR_ALLIANCE'."),
    )
    exclude_alliance: list[str] | None = Field(
        None,
        description="Alliance names to EXCLUDE from results.",
    )
    min_layover: int | None = Field(
        None,
        ge=1,
        description="Minimum layover duration in minutes (multi-stop trips only).",
    )
    max_layover: int | None = Field(
        None,
        ge=1,
        description="Maximum layover duration in minutes (multi-stop trips only).",
    )


class DateSearchParams(BaseModel):
    """Parameters for finding the cheapest travel dates within a range."""

    origin: str = Field(
        description="Departure airport IATA code(s), comma-separated for multiple (e.g., 'JFK,LGA')"
    )
    destination: str = Field(
        description="Arrival airport IATA code(s), comma-separated for multiple (e.g., 'LHR,CDG')"
    )
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
    currency: str | None = Field(
        None,
        description=(
            "ISO 4217 currency code (e.g. 'USD', 'EUR', 'GBP') to bill prices in. "
            "When omitted, Google picks based on locale (usually USD)."
        ),
    )
    language: str | None = Field(
        None,
        description="Optional BCP-47 language code (e.g. 'en-GB') passed to Google as `hl`.",
    )
    country: str | None = Field(
        None,
        description=(
            "Optional ISO 3166-1 alpha-2 country code (e.g. 'GB') for Google's `gl` param."
        ),
    )
    exclude_airlines: list[str] | None = Field(
        None,
        description="Airline IATA codes to EXCLUDE from results.",
    )
    alliance: list[str] | None = Field(
        None,
        description="Restrict to alliances: 'ONEWORLD', 'SKYTEAM', 'STAR_ALLIANCE'.",
    )
    exclude_alliance: list[str] | None = Field(
        None,
        description="Alliance names to EXCLUDE from results.",
    )
    min_layover: int | None = Field(
        None,
        ge=1,
        description="Minimum layover duration in minutes (multi-stop trips only).",
    )
    max_layover: int | None = Field(
        None,
        ge=1,
        description="Maximum layover duration in minutes (multi-stop trips only).",
    )


# =============================================================================
# Result Serialization
# =============================================================================


def _airline_code(airline: Any) -> str:
    return getattr(airline, "name", str(airline)).lstrip("_")


def _iata(airport: Any) -> str:
    """Return the bare IATA code from an ``Airport`` enum or plain string."""
    return getattr(airport, "name", str(airport)).lstrip("_")


def _google_flights_url(
    origins: list[Airport],
    destinations: list[Airport],
    departure_date: str,
    return_date: str | None,
    currency: str | None,
    language: str | None,
    country: str | None,
) -> str:
    """Build a shareable Google Flights deep link for the search.

    Thin wrapper over :func:`fli.core.google_flights_url` that takes the
    resolved airport lists used internally; the first airport of each side is
    used when multiple are given, keeping the query unambiguous for Google's
    parser.
    """
    return google_flights_url(
        _iata(origins[0]),
        _iata(destinations[0]),
        departure_date,
        return_date,
        currency=currency,
        language=language,
        country=country,
    )


def _serialize_booking_option(option: Any) -> dict[str, Any]:
    """Serialize a single bookable fare to a clean dictionary."""
    out: dict[str, Any] = {}
    for key in (
        "vendor_name",
        "vendor_code",
        "fare_name",
        "currency",
        "booking_url",
        "google_click_url",
    ):
        value = getattr(option, key, None)
        if value not in (None, ""):
            out[key] = value
    if getattr(option, "price", None) is not None:
        out["price"] = option.price
    if getattr(option, "is_airline_direct", False):
        out["is_airline_direct"] = True
    return out


def _flight_legs(flight: Any) -> list[Any]:
    """Flatten a result (or round-trip/multi-city tuple) into its legs."""
    if isinstance(flight, tuple):
        return [leg for segment in flight for leg in segment.legs]
    return list(flight.legs)


def _leg_identifiers(leg: Any) -> set[str]:
    """Return the accepted identifier spellings for a leg ('178' and 'BA178')."""
    number = str(leg.flight_number).upper().replace(" ", "")
    code = _airline_code(leg.airline).upper()
    # Strip a leading airline-code prefix if the flight_number already carries
    # it (e.g. "BA178" -> "178") so the bare and prefixed forms are always both
    # valid and we never produce a double-prefixed token ("BABA178").
    bare = number[len(code) :] if code and number.startswith(code) else number
    return {bare, f"{code}{bare}"}


def _match_flight(flights: list[Any], flight_numbers: list[str] | None) -> Any | None:
    """Pick the result matching ``flight_numbers`` (order-sensitive).

    Each entry is matched against either the bare flight number ('178') or
    the airline-prefixed form ('BA178'), case-insensitively. When no flight
    numbers are supplied the first result is returned (the top/cheapest row
    under the default sort).
    """
    if not flight_numbers:
        return flights[0] if flights else None
    want = [fn.upper().replace(" ", "") for fn in flight_numbers]
    for flight in flights:
        legs = _flight_legs(flight)
        if len(legs) != len(want):
            continue
        if all(token in _leg_identifiers(leg) for token, leg in zip(want, legs, strict=True)):
            return flight
    return None


def _flight_idents(flight: Any) -> list[str]:
    """Human-readable airline+number labels for each leg of a result."""
    return [f"{_airline_code(leg.airline)}{leg.flight_number}" for leg in _flight_legs(flight)]


def _serialize_flight_leg(leg: Any) -> dict[str, Any]:
    """Serialize a single flight leg to a dictionary."""
    out: dict[str, Any] = {
        "departure_airport": leg.departure_airport,
        "arrival_airport": leg.arrival_airport,
        "departure_time": leg.departure_datetime,
        "arrival_time": leg.arrival_datetime,
        "duration": leg.duration,
        "airline": leg.airline,
        "airline_code": _airline_code(leg.airline),
        "flight_number": leg.flight_number,
    }
    if getattr(leg, "departure_airport_name", None):
        out["departure_airport_name"] = leg.departure_airport_name
    if getattr(leg, "arrival_airport_name", None):
        out["arrival_airport_name"] = leg.arrival_airport_name
    if getattr(leg, "operating_airline", None):
        out["operating_airline"] = _airline_code(leg.operating_airline)
    if getattr(leg, "aircraft", None):
        out["aircraft"] = leg.aircraft
    if getattr(leg, "legroom", None):
        out["legroom"] = leg.legroom
    if getattr(leg, "overnight", False):
        out["overnight"] = True
    amenities = getattr(leg, "amenities", None)
    if amenities is not None:
        a = amenities.model_dump(exclude_none=True)
        if a:
            out["amenities"] = a
    return out


def _serialize_layover(layover: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "airport": _airline_code(layover.airport),
        "duration": layover.duration,
    }
    if layover.overnight:
        out["overnight"] = True
    if layover.change_of_airport:
        out["change_of_airport"] = True
    return out


def _flight_extras(flight: Any) -> dict[str, Any]:
    """Surface optional rich fields when populated by the parser.

    Emissions fields (``co2_emissions_g`` etc.) are deliberately omitted —
    the ``--emissions LESS`` filter still flows through to Google, but
    raw CO₂ numbers are not part of the tool's response shape.
    """
    out: dict[str, Any] = {}
    for src, key in (
        ("primary_airline_name", "primary_airline_name"),
        ("self_transfer", "self_transfer"),
        ("mixed_cabin", "mixed_cabin"),
    ):
        v = getattr(flight, src, None)
        if v is not None and v != "":
            out[key] = v
    primary = getattr(flight, "primary_airline", None)
    if primary is not None:
        out["primary_airline"] = _airline_code(primary)
    layovers = getattr(flight, "layovers", None)
    if layovers:
        out["layovers"] = [_serialize_layover(lo) for lo in layovers]
    return out


def _serialize_flight_result(
    flight: Any,
    is_round_trip: bool = False,
    *,
    booking_url: str | None = None,
) -> dict[str, Any]:
    """Serialize a flight result (or round-trip/multi-city tuple) to a dictionary."""
    if not isinstance(flight, tuple):
        out = {
            "price": flight.price,
            "currency": flight.currency or CONFIG.default_currency,
            "legs": [_serialize_flight_leg(leg) for leg in flight.legs],
        }
        out.update(_flight_extras(flight))
        if booking_url:
            out["booking_url"] = booking_url
        return out

    segments = list(flight)

    if len(segments) == 2 and is_round_trip:
        # Google Flights returns the full round-trip price on the outbound leg
        outbound, return_flight = segments
        out = {
            "price": outbound.price,
            "currency": outbound.currency or CONFIG.default_currency,
            "legs": [
                *[_serialize_flight_leg(leg) for leg in outbound.legs],
                *[_serialize_flight_leg(leg) for leg in return_flight.legs],
            ],
        }
        out.update(_flight_extras(outbound))
        return_extras = _flight_extras(return_flight)
        if return_extras:
            out["return_flight"] = return_extras
        if booking_url:
            out["booking_url"] = booking_url
        return out

    # Multi-city (3+ legs) or 2-leg non-round-trip: combined price on the
    # final leg (matches Google Flights pricing and the CLI display logic).
    price_segment = segments[-1] if len(segments) > 2 else segments[0]
    out = {
        "price": price_segment.price,
        "currency": price_segment.currency or CONFIG.default_currency,
        "legs": [_serialize_flight_leg(leg) for segment in segments for leg in segment.legs],
    }
    out.update(_flight_extras(price_segment))
    if booking_url:
        out["booking_url"] = booking_url
    return out


def _date_str(value: Any) -> str | None:
    """Coerce a ``DatePrice`` date element (datetime) to ``YYYY-MM-DD``."""
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)


def _serialize_date_result(
    date_result: Any,
    origins: list[Airport],
    destinations: list[Airport],
    locale: tuple[str | None, str | None, str | None],
) -> dict[str, Any]:
    """Serialize a date price result, including a deep link for that date."""
    dates = date_result.date
    departure = _date_str(dates[0]) if dates else None
    return_date = _date_str(dates[1]) if dates and len(dates) > 1 else None
    out: dict[str, Any] = {
        "date": departure,
        "price": date_result.price,
        "currency": date_result.currency or CONFIG.default_currency,
        "return_date": return_date,
    }
    if departure:
        out["booking_url"] = _google_flights_url(
            origins, destinations, departure, return_date, *locale
        )
    return out


# =============================================================================
# Search Execution
# =============================================================================


def _resolve_airports(codes: str) -> list[Airport]:
    """Resolve one or more comma-separated airport codes."""
    airports = [resolve_airport(code.strip()) for code in codes.split(",") if code.strip()]
    if not airports:
        raise ParseError(f"No valid airport codes found in: '{codes}'")
    return airports


def _build_flight_filters(
    params: FlightSearchParams,
) -> tuple[FlightSearchFilters, TripType, list[Airport], list[Airport]]:
    """Translate request params into search filters and resolved airports.

    Shared by :func:`_execute_flight_search` and
    :func:`_execute_booking_options` so both build identical filters from
    the same inputs.
    """
    # Parse inputs using shared utilities (supports comma-separated multi-airport)
    origins = _resolve_airports(params.origin)
    destinations = _resolve_airports(params.destination)
    cabin_class = parse_cabin_class(params.cabin_class)
    max_stops = parse_max_stops(params.max_stops)
    sort_by = parse_sort_by(params.sort_by)
    airlines = parse_airlines(params.airlines)
    airlines_exclude = parse_airlines(params.exclude_airlines)
    alliances = parse_alliances(params.alliance)
    alliances_exclude = parse_alliances(params.exclude_alliance)

    # Build time restrictions
    departure_window = params.departure_window or CONFIG.default_departure_window
    time_restrictions = build_time_restrictions(departure_window) if departure_window else None

    # Build flight segments (pass full lists for multi-airport support)
    segments, trip_type = build_flight_segments(
        origin=origins,
        destination=destinations,
        departure_date=params.departure_date,
        return_date=params.return_date,
        time_restrictions=time_restrictions,
    )

    # Parse new filters
    emissions_filter = parse_emissions(params.emissions)
    bags_filter = None
    if params.checked_bags > 0 or params.carry_on:
        bags_filter = BagsFilter(checked_bags=params.checked_bags, carry_on=params.carry_on)

    layover_restrictions = None
    if params.min_layover is not None or params.max_layover is not None:
        from fli.models import LayoverRestrictions

        layover_restrictions = LayoverRestrictions(
            min_duration=params.min_layover,
            max_duration=params.max_layover,
        )

    filters = FlightSearchFilters(
        trip_type=trip_type,
        passenger_info=PassengerInfo(adults=params.passengers),
        flight_segments=segments,
        stops=max_stops,
        seat_type=cabin_class,
        airlines=airlines,
        airlines_exclude=airlines_exclude,
        alliances=alliances,
        alliances_exclude=alliances_exclude,
        layover_restrictions=layover_restrictions,
        sort_by=sort_by,
        exclude_basic_economy=params.exclude_basic_economy,
        emissions=emissions_filter,
        bags=bags_filter,
        show_all_results=params.show_all_results,
    )
    return filters, trip_type, origins, destinations


def _execute_flight_search(params: FlightSearchParams) -> dict[str, Any]:
    """Execute a flight search and return formatted results."""
    try:
        filters, trip_type, origins, destinations = _build_flight_filters(params)

        # Perform search
        currency = parse_currency(params.currency)
        search_client = SearchFlights()
        flights = search_client.search(
            filters,
            currency=currency,
            language=params.language,
            country=params.country,
        )

        booking_url = _google_flights_url(
            origins,
            destinations,
            params.departure_date,
            params.return_date,
            params.currency,
            params.language,
            params.country,
        )

        if not flights:
            return {
                "success": True,
                "flights": [],
                "count": 0,
                "trip_type": trip_type.name,
                "booking_url": booking_url,
            }

        # Serialize results; attach per-flight deep-link booking URL.
        is_round_trip = trip_type == TripType.ROUND_TRIP
        flight_results = [
            _serialize_flight_result(
                f,
                is_round_trip,
                booking_url=search_client.build_flight_booking_url(
                    f,
                    currency=params.currency,
                    language=params.language,
                    country=params.country,
                ),
            )
            for f in flights
        ]

        if CONFIG.max_results:
            flight_results = flight_results[: CONFIG.max_results]

        return {
            "success": True,
            "flights": flight_results,
            "count": len(flight_results),
            "trip_type": trip_type.name,
            "booking_url": booking_url,
        }

    except ParseError as e:
        return {"success": False, "error": str(e), "flights": []}
    except Exception as e:
        error_msg = str(e)
        if "validation error" in error_msg.lower():
            return {"success": False, "error": "Invalid parameter value", "flights": []}
        return {"success": False, "error": f"Search failed: {error_msg}", "flights": []}


def _execute_booking_options(
    params: FlightSearchParams, flight_numbers: list[str] | None
) -> dict[str, Any]:
    """Fetch real bookable fares (vendor URLs + prices) for one itinerary.

    Re-runs the search so the client captures a fresh shopping session,
    selects the itinerary identified by ``flight_numbers`` (or the top
    result when omitted), then calls
    :meth:`fli.search.SearchFlights.get_booking_options` and serializes the
    vendor list — each carrying a direct ``booking_url``.
    """
    try:
        filters, trip_type, origins, destinations = _build_flight_filters(params)

        currency = parse_currency(params.currency)
        search_client = SearchFlights()
        flights = search_client.search(
            filters,
            currency=currency,
            language=params.language,
            country=params.country,
        )

        booking_url = _google_flights_url(
            origins,
            destinations,
            params.departure_date,
            params.return_date,
            params.currency,
            params.language,
            params.country,
        )

        if not flights:
            return {"success": True, "options": [], "count": 0, "booking_url": booking_url}

        flight = _match_flight(flights, flight_numbers)
        if flight is None:
            return {
                "success": False,
                "error": (
                    "No flight matched the requested flight_numbers. Pass values "
                    "from a prior search_flights result (e.g. ['BA178'] or ['178'])."
                ),
                "available_flights": [_flight_idents(f) for f in flights[:20]],
                "options": [],
                "booking_url": booking_url,
            }

        options = search_client.get_booking_options(
            flight,
            filters,
            currency=currency,
            language=params.language,
            country=params.country,
        )

        is_round_trip = trip_type == TripType.ROUND_TRIP
        flight_booking_url = search_client.build_flight_booking_url(
            flight,
            currency=params.currency,
            language=params.language,
            country=params.country,
        )
        serialized = [_serialize_booking_option(o) for o in options]
        result = {
            "success": True,
            "selected_flight": _serialize_flight_result(
                flight, is_round_trip, booking_url=flight_booking_url
            ),
            "options": serialized,
            "count": len(serialized),
            "booking_url": booking_url,
        }
        if not serialized:
            # Google's GetBookingResults frequently returns no vendors without a
            # browser-minted session token that fli does not reproduce server-side.
            # The per-flight deep link in selected_flight.booking_url opens the
            # specific itinerary's booking page directly.
            result["note"] = (
                "Google returned no per-vendor booking fares for this itinerary. "
                "Use selected_flight.booking_url to open the specific flight's "
                "booking page on Google Flights."
            )
        return result

    except ParseError as e:
        return {"success": False, "error": str(e), "options": []}
    except Exception as e:
        error_msg = str(e)
        if "validation error" in error_msg.lower():
            return {"success": False, "error": "Invalid parameter value", "options": []}
        return {"success": False, "error": f"Booking lookup failed: {error_msg}", "options": []}


def _execute_date_search(params: DateSearchParams) -> dict[str, Any]:
    """Execute a date search and return formatted results."""
    try:
        # Parse inputs using shared utilities (supports comma-separated multi-airport)
        origins = _resolve_airports(params.origin)
        destinations = _resolve_airports(params.destination)
        cabin_class = parse_cabin_class(params.cabin_class)
        max_stops = parse_max_stops(params.max_stops)
        airlines = parse_airlines(params.airlines)
        airlines_exclude = parse_airlines(params.exclude_airlines)
        alliances = parse_alliances(params.alliance)
        alliances_exclude = parse_alliances(params.exclude_alliance)

        # Build time restrictions
        departure_window = params.departure_window or CONFIG.default_departure_window
        time_restrictions = build_time_restrictions(departure_window) if departure_window else None

        # Build flight segments (pass full lists for multi-airport support)
        segments, trip_type = build_date_search_segments(
            origin=origins,
            destination=destinations,
            start_date=params.start_date,
            trip_duration=params.trip_duration,
            is_round_trip=params.is_round_trip,
            time_restrictions=time_restrictions,
        )

        layover_restrictions = None
        if params.min_layover is not None or params.max_layover is not None:
            from fli.models import LayoverRestrictions

            layover_restrictions = LayoverRestrictions(
                min_duration=params.min_layover,
                max_duration=params.max_layover,
            )

        # Create search filters
        filters = DateSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=params.passengers),
            flight_segments=segments,
            stops=max_stops,
            seat_type=cabin_class,
            airlines=airlines,
            airlines_exclude=airlines_exclude,
            alliances=alliances,
            alliances_exclude=alliances_exclude,
            layover_restrictions=layover_restrictions,
            from_date=params.start_date,
            to_date=params.end_date,
            duration=params.trip_duration if params.is_round_trip else None,
        )

        # Perform search
        currency = parse_currency(params.currency)
        search_client = SearchDates()
        dates = search_client.search(
            filters,
            currency=currency,
            language=params.language,
            country=params.country,
        )

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
        locale = (params.currency, params.language, params.country)
        date_results = [_serialize_date_result(d, origins, destinations, locale) for d in dates]

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
    origin: Annotated[
        str,
        Field(
            description="Departure airport IATA code(s), comma-separated for multiple "
            "(e.g., 'JFK' or 'JFK,LGA')"
        ),
    ],
    destination: Annotated[
        str,
        Field(
            description="Arrival airport IATA code(s), comma-separated for multiple "
            "(e.g., 'LHR' or 'LHR,CDG')"
        ),
    ],
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
    currency: Annotated[
        str | None,
        Field(
            description=(
                "ISO 4217 currency code (USD, EUR, GBP, JPY...) for prices. "
                "When omitted, Google picks based on locale."
            )
        ),
    ] = None,
    language: Annotated[
        str | None,
        Field(description="Optional BCP-47 language code (e.g., 'en-GB') for the `hl` URL param."),
    ] = None,
    country: Annotated[
        str | None,
        Field(description="Optional ISO 3166-1 alpha-2 country code (e.g., 'GB')."),
    ] = None,
    exclude_airlines: Annotated[
        list[str] | None,
        Field(description="Airline IATA codes to EXCLUDE from results."),
    ] = None,
    alliance: Annotated[
        list[str] | None,
        Field(description="Restrict to alliances: ONEWORLD, SKYTEAM, STAR_ALLIANCE."),
    ] = None,
    exclude_alliance: Annotated[
        list[str] | None,
        Field(description="Alliance names to EXCLUDE from results."),
    ] = None,
    min_layover: Annotated[
        int | None,
        Field(description="Minimum layover duration in minutes.", ge=1),
    ] = None,
    max_layover: Annotated[
        int | None,
        Field(description="Maximum layover duration in minutes.", ge=1),
    ] = None,
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
        currency=currency,
        language=language,
        country=country,
        exclude_airlines=exclude_airlines,
        alliance=alliance,
        exclude_alliance=exclude_alliance,
        min_layover=min_layover,
        max_layover=max_layover,
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
    origin: Annotated[
        str,
        Field(
            description="Departure airport IATA code(s), comma-separated for multiple "
            "(e.g., 'JFK' or 'JFK,LGA')"
        ),
    ],
    destination: Annotated[
        str,
        Field(
            description="Arrival airport IATA code(s), comma-separated for multiple "
            "(e.g., 'LHR' or 'LHR,CDG')"
        ),
    ],
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
    currency: Annotated[
        str | None,
        Field(description="ISO 4217 currency code (USD, EUR, GBP, JPY...) for prices."),
    ] = None,
    language: Annotated[
        str | None,
        Field(description="Optional BCP-47 language code (e.g., 'en-GB') for the `hl` URL param."),
    ] = None,
    country: Annotated[
        str | None,
        Field(description="Optional ISO 3166-1 alpha-2 country code (e.g., 'GB')."),
    ] = None,
    exclude_airlines: Annotated[
        list[str] | None,
        Field(description="Airline IATA codes to EXCLUDE from results."),
    ] = None,
    alliance: Annotated[
        list[str] | None,
        Field(description="Restrict to alliances: ONEWORLD, SKYTEAM, STAR_ALLIANCE."),
    ] = None,
    exclude_alliance: Annotated[
        list[str] | None,
        Field(description="Alliance names to EXCLUDE from results."),
    ] = None,
    min_layover: Annotated[
        int | None,
        Field(description="Minimum layover duration in minutes.", ge=1),
    ] = None,
    max_layover: Annotated[
        int | None,
        Field(description="Maximum layover duration in minutes.", ge=1),
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
        currency=currency,
        language=language,
        country=country,
        exclude_airlines=exclude_airlines,
        alliance=alliance,
        exclude_alliance=exclude_alliance,
        min_layover=min_layover,
        max_layover=max_layover,
    )
    return _execute_date_search(params)


def _search_dates_from_params(params: DateSearchParams) -> dict[str, Any]:
    """Entry point for tests that call the tool via a params object."""
    return _execute_date_search(params)


@mcp.tool(
    annotations={
        "title": "Get Booking Options",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
def get_booking_options(
    origin: Annotated[
        str,
        Field(description="Departure airport IATA code(s), comma-separated for multiple"),
    ],
    destination: Annotated[
        str,
        Field(description="Arrival airport IATA code(s), comma-separated for multiple"),
    ],
    departure_date: Annotated[str, Field(description="Travel date in YYYY-MM-DD format")],
    flight_numbers: Annotated[
        list[str] | None,
        Field(
            description=(
                "Flight numbers identifying the itinerary to price, in order, taken from a "
                "prior search_flights result (e.g. ['BA178'] one-way, ['AA100', 'AA200'] "
                "round-trip). Accepts bare numbers ('178') or airline-prefixed ('BA178'). "
                "Omit to price the top result."
            )
        ),
    ] = None,
    return_date: Annotated[
        str | None,
        Field(description="Return date in YYYY-MM-DD format (omit for one-way)"),
    ] = None,
    cabin_class: Annotated[
        str,
        Field(description="Cabin class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST"),
    ] = CONFIG.default_cabin_class,
    max_stops: Annotated[
        str,
        Field(description="Maximum stops: ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS"),
    ] = "ANY",
    passengers: Annotated[
        int | None,
        Field(description="Number of adult passengers", ge=1),
    ] = None,
    airlines: Annotated[
        list[str] | None,
        Field(description="Filter by airline IATA codes (e.g., ['BA', 'AA'])"),
    ] = None,
    exclude_basic_economy: Annotated[
        bool,
        Field(description="Exclude basic economy fares from results"),
    ] = False,
    currency: Annotated[
        str | None,
        Field(description="ISO 4217 currency code (USD, EUR, GBP, JPY...) for prices."),
    ] = None,
    language: Annotated[
        str | None,
        Field(description="Optional BCP-47 language code (e.g., 'en-GB') for the `hl` URL param."),
    ] = None,
    country: Annotated[
        str | None,
        Field(description="Optional ISO 3166-1 alpha-2 country code (e.g., 'GB')."),
    ] = None,
    departure_window: Annotated[
        str | None,
        Field(description="Departure time window in 'HH-HH' 24h format (e.g., '6-20')"),
    ] = None,
    sort_by: Annotated[
        str,
        Field(
            description="Sort by: TOP_FLIGHTS, BEST, CHEAPEST,"
            " DEPARTURE_TIME, ARRIVAL_TIME, DURATION, EMISSIONS"
        ),
    ] = CONFIG.default_sort_by,
    exclude_airlines: Annotated[
        list[str] | None,
        Field(description="Airline IATA codes to EXCLUDE from results."),
    ] = None,
    alliance: Annotated[
        list[str] | None,
        Field(description="Restrict to alliances: ONEWORLD, SKYTEAM, STAR_ALLIANCE."),
    ] = None,
    exclude_alliance: Annotated[
        list[str] | None,
        Field(description="Alliance names to EXCLUDE from results."),
    ] = None,
    min_layover: Annotated[
        int | None,
        Field(description="Minimum layover duration in minutes.", ge=1),
    ] = None,
    max_layover: Annotated[
        int | None,
        Field(description="Maximum layover duration in minutes.", ge=1),
    ] = None,
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
) -> dict[str, Any]:
    """Get bookable fares (vendor names, prices, and direct booking URLs) for a flight.

    Runs a fresh search, selects the itinerary identified by ``flight_numbers``
    (or the top result when omitted), and returns the airline-direct and
    online-travel-agency options Google surfaces for it — each with a
    clickable ``booking_url``. Use ``search_flights`` first to discover the
    flight numbers, then call this tool to retrieve where and at what price
    it can be booked.

    Pass the same filters (``sort_by``, ``departure_window``,
    ``exclude_airlines``, ``alliance``, layover/bags/emissions, …) that were
    used for ``search_flights`` so the re-run search reproduces the same result
    set — otherwise, when ``flight_numbers`` is omitted, the priced "top
    result" may differ from the one the user saw.
    """
    effective_departure_window = departure_window or CONFIG.default_departure_window
    params = FlightSearchParams(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        departure_window=effective_departure_window,
        cabin_class=cabin_class,
        max_stops=max_stops,
        sort_by=sort_by,
        passengers=passengers or CONFIG.default_passengers,
        airlines=airlines,
        exclude_basic_economy=exclude_basic_economy,
        emissions=emissions,
        checked_bags=checked_bags,
        carry_on=carry_on,
        currency=currency,
        language=language,
        country=country,
        exclude_airlines=exclude_airlines,
        alliance=alliance,
        exclude_alliance=exclude_alliance,
        min_layover=min_layover,
        max_layover=max_layover,
    )
    return _execute_booking_options(params, flight_numbers)


def _get_booking_options_from_params(
    params: FlightSearchParams, flight_numbers: list[str] | None = None
) -> dict[str, Any]:
    """Entry point for tests that call the tool via a params object."""
    return _execute_booking_options(params, flight_numbers)


def _find_airports_impl(query: str, limit: int = 10) -> dict[str, Any]:
    """Run search_airports and shape the result into the MCP response dict."""
    try:
        results = search_airports(query, limit=limit)
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "query": query,
        }

    return {
        "success": True,
        "query": query,
        "count": len(results),
        "airports": [
            {"code": r.code.name, "name": r.name, "match_type": r.match_type} for r in results
        ],
    }


@mcp.tool(
    annotations={
        "title": "Search Airports",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
def find_airports(
    query: Annotated[
        str,
        Field(
            description=(
                "City name, airport name, or IATA code (e.g., 'new york', 'heathrow', 'JFK')"
            )
        ),
    ],
    limit: Annotated[int, Field(description="Maximum results to return", ge=1, le=50)] = 10,
) -> dict[str, Any]:
    """Search for airports by city name, airport name, or IATA code.

    Use this tool to find airport IATA codes before searching for flights.
    Supports city names (e.g., "new york" returns JFK, LGA, EWR),
    airport names (e.g., "heathrow" returns LHR), and IATA codes.
    """
    return _find_airports_impl(query, limit=limit)


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


def run_http(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the MCP server over HTTP (streamable).

    The default host is ``0.0.0.0`` so the server is reachable from outside the
    container when deployed (e.g. Railway, Docker). When running locally this
    exposes the server on every network interface — set ``HOST=127.0.0.1`` to
    restrict it to loopback.
    """
    env_host = os.getenv("HOST")
    env_port = os.getenv("PORT")

    bind_host = env_host if env_host else host
    bind_port = int(env_port) if env_port else port

    mcp.run(transport="http", host=bind_host, port=bind_port)


if __name__ == "__main__":
    run()
