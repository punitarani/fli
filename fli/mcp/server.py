"""Flight Search MCP Server.

This module provides an MCP (Model Context Protocol) server for flight search
functionality, enabling AI assistants to search for flights and find cheapest
travel dates.
"""

import json
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from fli.core import (
    build_date_search_segments,
    build_flight_segments,
    build_multi_city_segments,
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


class MultiCityLeg(BaseModel):
    """A single leg of a multi-city itinerary."""

    origin: str = Field(description="Departure airport IATA code (e.g., 'JFK')")
    destination: str = Field(description="Arrival airport IATA code (e.g., 'LHR')")
    date: str = Field(description="Travel date in YYYY-MM-DD format")


class MultiCitySearchParams(BaseModel):
    """Parameters for searching multi-city flights."""

    legs: list[MultiCityLeg] = Field(
        description="List of flight legs, each with origin, destination, and date",
        min_length=2,
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


def _normalize_flight_prices(
    flight_results: list[dict[str, Any]], sort_by: Any = None,
) -> list[dict[str, Any]]:
    """Tag price-unavailable entries and ensure they don't pollute CHEAPEST sort.

    Google Flights occasionally returns options with no displayable price
    (parsed as ``0.0`` upstream).  Previously these were rewritten to
    ``price: null`` and left interleaved with priced results — meaning a
    CHEAPEST sort surfaced a None-priced option as the "top" hit (which
    mis-suggests "no usable options" when in fact priced alternatives exist
    further down the list).  We now:

    1. Set ``price`` to ``None`` and add an explicit ``price_unavailable:
       True`` flag so callers can branch on it.
    2. When ``sort_by`` is CHEAPEST, push price-unavailable entries to the
       end so the first option the LLM sees is always actionable.
    """
    for fr in flight_results:
        price = fr.get("price")
        if price is None or price == 0:
            fr["price"] = None
            fr["price_unavailable"] = True
        else:
            fr["price_unavailable"] = False

    sort_name = getattr(sort_by, "name", None)
    if sort_name == "CHEAPEST":
        # Stable sort: priced entries keep their server-side order; unpriced
        # entries get pushed to the bottom in original order.
        flight_results.sort(key=lambda fr: 1 if fr.get("price_unavailable") else 0)

    return flight_results


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


def _classify_search_error(exc: Exception) -> dict[str, Any]:
    """Classify a search exception so callers can distinguish a true zero-result
    response from a network/API failure.

    Without this, a 30-60s timeout against Google Flights and a search that
    legitimately returns zero options both surface to the LLM as
    ``flights:[]``, which is easy to misread as "the requested itinerary is
    impossible" when in fact a retry might succeed.  This is especially
    important for multi-city searches: Google's continuation endpoint
    (``GetShoppingResults`` with ``selected_flight`` set) is intermittently
    slow, and a transient timeout should not be reported the same way as
    "no airline files this routing".
    """
    msg = str(exc)
    lower = msg.lower()
    # curl-cffi surfaces a CURLE_OPERATION_TIMEDOUT (curl error 28) as a
    # ``Timeout`` exception whose message contains "timed out".  Both the
    # canonical phrase and the curl error number are checked because the
    # exception is re-wrapped by ``Client.post`` into a generic ``Exception``.
    is_timeout = "timed out" in lower or "curl: (28)" in lower
    if is_timeout:
        return {
            "success": False,
            "error_kind": "timeout",
            "error": (
                "Google Flights API timed out. Multi-city continuation calls"
                " (when previous legs are selected) are intermittently slow."
                " Retry the same request — this is not a 'no flights' result."
            ),
            "flights": [],
        }
    if "validation error" in lower:
        return {
            "success": False,
            "error_kind": "validation",
            "error": "Invalid parameter value",
            "flights": [],
        }
    return {
        "success": False,
        "error_kind": "unknown",
        "error": f"Search failed: {msg}",
        "flights": [],
    }


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
        flight_results = _normalize_flight_prices(flight_results, sort_by=sort_by)

        if CONFIG.max_results:
            flight_results = flight_results[: CONFIG.max_results]

        return {
            "success": True,
            "flights": flight_results,
            "count": len(flight_results),
            "trip_type": trip_type.name,
        }

    except ParseError as e:
        return {"success": False, "error_kind": "parse", "error": str(e), "flights": []}
    except Exception as e:
        return _classify_search_error(e)


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
        return {"success": False, "error_kind": "parse", "error": str(e), "dates": []}
    except Exception as e:
        # Reuse the same classifier; swap the empty key from ``flights`` to
        # ``dates`` so the response shape stays consistent for date searches.
        resp = _classify_search_error(e)
        resp["dates"] = resp.pop("flights", [])
        return resp


# =============================================================================
# Multi-City Search (stateful, one API call per step)
# =============================================================================

_search_sessions: dict[str, tuple[Any, list[Any]]] = {}


def _session_key(legs: list[MultiCityLeg]) -> str:
    return "|".join(
        f"{leg.origin}-{leg.destination}-{leg.date}" for leg in legs
    )


def _build_per_leg_fallback_filters(
    filters: FlightSearchFilters, current_step: int,
) -> FlightSearchFilters:
    """Build a one-way filter for a single leg of a multi-city itinerary.

    Used when Google's multi-city curator returns empty or only-unpriced
    options — common on 4+-leg itineraries where the curator appears to
    restrict candidates to single-carrier or alliance bundles, dropping
    carriers that price fine standalone (e.g., CZ on a routing where
    Star Alliance carriers cover every city).  The fallback surfaces the
    same options the one-way ``search_flights`` path returns, at the
    cost of a combined trip price.
    """
    current_segment = deepcopy(filters.flight_segments[current_step])
    current_segment.selected_flight = None
    return FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=filters.passenger_info,
        flight_segments=[current_segment],
        stops=filters.stops,
        seat_type=filters.seat_type,
        airlines=filters.airlines,
        sort_by=filters.sort_by,
        exclude_basic_economy=filters.exclude_basic_economy,
        emissions=filters.emissions,
        bags=filters.bags,
        show_all_results=filters.show_all_results,
    )


def _all_unpriced(raw: list[Any]) -> bool:
    """Check whether every parsed FlightResult in *raw* lacks a usable price."""
    return all((getattr(r, "price", 0) or 0) == 0 for r in raw)


def _execute_multi_city_step(
    params: MultiCitySearchParams, selection: int | None,
) -> dict[str, Any]:
    """Execute one step of a multi-city search. Exactly one API call per invocation."""
    key = _session_key(params.legs)

    try:
        cached = _search_sessions.get(key)

        if cached is None or selection is None:
            cabin_class = parse_cabin_class(params.cabin_class)
            max_stops = parse_max_stops(params.max_stops)
            sort_by = parse_sort_by(params.sort_by)
            airlines = parse_airlines(params.airlines)

            departure_window = (
                params.departure_window or CONFIG.default_departure_window
            )
            time_restrictions = (
                build_time_restrictions(departure_window)
                if departure_window
                else None
            )

            resolved_legs = [
                (resolve_airport(leg.origin), resolve_airport(leg.destination), leg.date)
                for leg in params.legs
            ]

            segments, trip_type = build_multi_city_segments(
                legs=resolved_legs,
                time_restrictions=time_restrictions,
            )

            emissions_filter = parse_emissions(params.emissions)
            bags_filter = None
            if params.checked_bags > 0 or params.carry_on:
                bags_filter = BagsFilter(checked_bags=params.checked_bags, carry_on=params.carry_on)

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
            current_step = 0
        else:
            filters, last_results = cached
            current_step = sum(
                1 for s in filters.flight_segments if s.selected_flight is not None
            )

            if selection >= len(last_results):
                return {
                    "success": False,
                    "error": (
                        f"Selection index {selection} out of range"
                        f" ({len(last_results)} options)"
                    ),
                    "flights": [],
                }

            filters = deepcopy(filters)
            filters.flight_segments[current_step].selected_flight = last_results[selection]
            current_step += 1

        search_client = SearchFlights()
        result = search_client._do_single_search(filters, include_metadata=True)
        if result is None:
            raw, metadata = [], {}
        else:
            raw, metadata = result

        num_legs = len(params.legs)
        is_final = current_step >= num_legs - 1

        # Per-leg fallback: when Google's multi-city curator returns empty
        # or only-unpriced options for this leg (common on 4+-leg trips
        # where the curator restricts to single-carrier/alliance bundles),
        # re-run as a standalone one-way query for the current leg.  We
        # lose the combined trip price but surface options the user can
        # actually pick — see the bug report where CZ disappeared from a
        # 4-leg LGW↔China itinerary even though every leg priced fine via
        # ``search_flights``.
        fallback_used = False
        if not raw or _all_unpriced(raw):
            fallback_filters = _build_per_leg_fallback_filters(filters, current_step)
            fb_result = search_client._do_single_search(
                fallback_filters, include_metadata=True,
            )
            if fb_result is not None:
                fb_raw, _ = fb_result
                # Only switch to the fallback if it actually surfaced priced
                # options; an empty/all-unpriced fallback is no improvement
                # over what we already have.
                if fb_raw and not _all_unpriced(fb_raw):
                    raw = fb_raw
                    metadata = {}  # multi-city price_range no longer applies
                    fallback_used = True

        if not raw:
            # Multi-city queries against ``GetShoppingResults`` regularly
            # return HTTP 200 + empty body on cold cache (~60 s server-side
            # timeout).  fli already retries empty multi-leg responses once
            # at the API layer; if we still ended up empty (and the per-leg
            # fallback also turned up nothing) the agent should know it's
            # likely transient and retry the same MCP call rather than
            # concluding the routing is impossible.  Keep the session so
            # the retry resumes from the same step.
            return {
                "success": True,
                "flights": [],
                "count": 0,
                "step": current_step + 1,
                "total_legs": num_legs,
                "is_final": is_final,
                "hint": (
                    "Empty result on a multi-city leg often means Google's"
                    " backend timed out warming a cold cache. Retry the"
                    " same call (without changing parameters) once or twice"
                    " — empirically a 4-leg query may need 2-4 attempts"
                    " before the warm path returns flights."
                ),
            }

        _search_sessions[key] = (filters, raw)

        flight_results = [_serialize_flight_result(f, is_round_trip=False) for f in raw]
        flight_results = _normalize_flight_prices(
            flight_results, sort_by=filters.sort_by,
        )

        if fallback_used:
            for fr in flight_results:
                fr["per_leg_price"] = True

        if CONFIG.max_results:
            flight_results = flight_results[: CONFIG.max_results]

        if is_final:
            _search_sessions.pop(key, None)

        resp: dict[str, Any] = {
            "success": True,
            "flights": flight_results,
            "count": len(flight_results),
            "step": current_step + 1,
            "total_legs": num_legs,
            "leg": (
                f"{params.legs[current_step].origin}"
                f" -> {params.legs[current_step].destination}"
                f" ({params.legs[current_step].date})"
            ),
            "is_final": is_final,
            "combined_pricing": not fallback_used,
        }

        price_range = metadata.get("price_range")
        if price_range and len(price_range) >= 2:
            resp["price_range"] = {"min": price_range[0], "max": price_range[1]}

        if fallback_used:
            resp["message"] = (
                f"Google's multi-city pricing was unavailable for leg"
                f" {current_step + 1} of {num_legs} — common on 4+-leg"
                " itineraries where the curator restricts to single-carrier"
                " bundles. Showing per-leg standalone prices instead; the"
                " combined trip total won't be available, so sum the"
                " individual leg prices to estimate the trip cost."
                + (
                    f" Pick a flight by index (0-{len(flight_results)-1})"
                    " and call again with selection=<index>."
                    if not is_final
                    else ""
                )
            )
        elif is_final:
            resp["message"] = (
                f"Showing options for leg {current_step + 1} of"
                f" {num_legs}. These are the final results."
                " price_range shows the total combined price"
                " range for the entire trip."
            )
        else:
            resp["message"] = (
                f"Showing options for leg {current_step + 1} of"
                f" {num_legs}. Pick a flight by index"
                f" (0-{len(flight_results)-1}) and call again"
                " with selection=<index>."
            )

        return resp

    except ParseError as e:
        _search_sessions.pop(key, None)
        return {"success": False, "error_kind": "parse", "error": str(e), "flights": []}
    except Exception as e:
        # Only discard the cached session on non-recoverable errors.  A
        # transient timeout on, say, the leg-3 continuation call should
        # *not* force the user to start over from leg 1 — keep the cached
        # filters + last_results so the next ``selection`` resumes cleanly.
        result = _classify_search_error(e)
        if result.get("error_kind") != "timeout":
            _search_sessions.pop(key, None)
        return result


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


@mcp.tool(
    annotations={
        "title": "Search Multi-City Flights",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
def search_multi_city(
    legs: Annotated[
        list[dict[str, str]],
        Field(
            description=(
                "List of flight legs. Each leg is an object with 'origin' (IATA code), "
                "'destination' (IATA code), and 'date' (YYYY-MM-DD). "
                "Example: [{'origin': 'JFK', 'destination': 'LHR', 'date': '2026-06-01'}, "
                "{'origin': 'LHR', 'destination': 'CDG', 'date': '2026-06-05'}]"
            ),
            min_length=2,
        ),
    ],
    selection: Annotated[
        int | str | None,
        Field(
            description=(
                "Index of the flight to select for the CURRENT leg (0-based). "
                "Omit for the first call to get leg 1 options. "
                "After reviewing results, pass the index of your chosen flight "
                "to advance to the next leg. The server remembers previous selections."
            ),
        ),
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
    """Search for multi-city flights step by step, one leg at a time.

    Works like Google Flights: first call returns options for leg 1.
    Pick a flight by index, pass it as selection, and call again to
    get options for leg 2 (with combined pricing), and so on.
    The server remembers your previous selections between calls.

    Response includes price_range (min/max for the total trip) when
    available from Google Flights.

    Example for a 3-leg trip:
      1. Call with legs=[...] (no selection) -> leg 1 options
      2. Call with legs=[...], selection=0 -> leg 2 options
      3. Call with legs=[...], selection=2 -> leg 3 final results with total pricing

    """
    effective_departure_window = departure_window or CONFIG.default_departure_window
    parsed_legs = [MultiCityLeg(**leg) for leg in legs]
    params = MultiCitySearchParams(
        legs=parsed_legs,
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
    sel = int(selection) if selection is not None else None
    return _execute_multi_city_step(params, sel)


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
