"""Opt-in hosted fallback for one-way searches Google refuses to serve.

Google answers the search page with HTTP 429 (or a page with no results) for
whole IP ranges: cloud and datacenter hosts, VPN exits, shared corporate NAT
(see #203). Nothing in the request fixes that, so the only way through is a
different address.

When ``FLI_APIFY_TOKEN`` is set, :meth:`fli.search.SearchFlights.search`
retries a blocked one-way economy search once through the Google Flights API
Actor on Apify (``johnvc/Google-Flights-Data-Scraper-Flight-and-Price-Search``),
billed to that token's Apify account (about $0.02-0.03 a search). The rows
come back as ordinary :class:`~fli.models.FlightResult` objects and go
through the same client-side filters and sort as a direct search.

With the variable unset nothing changes. Round trips, multi-city and premium
cabins never fall back: the Actor's input has no cabin field, and a round
trip would need a second hosted call per outbound. If the fallback itself
fails, the original error is raised, so existing error handling still sees
the error it expects.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from fli.models import FlightLeg, FlightResult, FlightSearchFilters, Layover
from fli.models.google_flights.base import MaxStops, SeatType, TripType
from fli.search._decoders import _parse_airline, _parse_airport
from fli.search.exceptions import (
    SearchClientError,
    SearchHTTPError,
    SearchParseError,
    SearchRejectedError,
)

logger = logging.getLogger(__name__)

TOKEN_ENV_VAR = "FLI_APIFY_TOKEN"
ACTOR = "johnvc~Google-Flights-Data-Scraper-Flight-and-Price-Search"
RUN_URL = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
# A hosted search usually finishes in under 10s; the run-sync endpoint
# itself gives up at 300s.
TIMEOUT = 120.0

# HTTP statuses that mean "this address is blocked", not "the query is wrong".
_BLOCKED_STATUSES = frozenset({403, 429})
_MAX_STOPS = {
    MaxStops.NON_STOP: 0,
    MaxStops.ONE_STOP_OR_FEWER: 1,
    MaxStops.TWO_OR_FEWER_STOPS: 2,
}
# The Actor's ``gl`` / ``hl`` enums. Anything else is left to its defaults.
_COUNTRIES = frozenset(
    "us uk ca au de fr es it nl pl br ru jp kr cn tw in sa tr se dk no fi cz hu ro mx ar "
    "ch at be ie nz sg my th ph id vn".split()
)
_LANGUAGES = frozenset(
    "en es fr de it pt ru ja ko zh ar hi tr pl nl sv da no fi cs hu ro el th vi id ms he uk".split()
)


def fallback_token() -> str | None:
    """Return the Apify token from ``FLI_APIFY_TOKEN``, or ``None`` when unset."""
    return os.environ.get(TOKEN_ENV_VAR, "").strip() or None


def is_blocked(exc: BaseException) -> bool:
    """Whether ``exc`` is Google refusing the request rather than a bad query."""
    if isinstance(exc, SearchHTTPError):
        return exc.status_code in _BLOCKED_STATUSES
    return isinstance(exc, SearchRejectedError | SearchParseError)


def can_fall_back(filters: FlightSearchFilters) -> bool:
    """Whether the hosted Actor can answer ``filters`` faithfully."""
    return (
        filters.trip_type == TripType.ONE_WAY
        and len(filters.flight_segments) == 1
        and filters.seat_type == SeatType.ECONOMY
    )


def _codes(airports: list[list[Any]]) -> str:
    return ",".join(entry[0].name for entry in airports if entry and hasattr(entry[0], "name"))


def actor_input(
    filters: FlightSearchFilters,
    *,
    currency: str | None = None,
    language: str | None = None,
    country: str | None = None,
) -> dict[str, Any]:
    """Translate one-way ``filters`` into the Actor's input.

    Airline include/exclude, price, duration and time windows are not sent:
    the caller applies ``apply_client_side_filters`` to the rows afterwards,
    exactly as it does for a direct search.
    """
    segment = filters.flight_segments[0]
    passengers = filters.passenger_info
    body: dict[str, Any] = {
        "departure_id": _codes(segment.departure_airport),
        "arrival_id": _codes(segment.arrival_airport),
        "outbound_date": segment.travel_date,
        "adults": max(passengers.adults, 1),
        "children": passengers.children,
        "infants": passengers.infants_in_seat + passengers.infants_on_lap,
        "currency": (currency or "USD").upper(),
        "exclude_basic": filters.exclude_basic_economy,
        "max_pages": 1,
    }
    if filters.stops in _MAX_STOPS:
        body["max_stops"] = _MAX_STOPS[filters.stops]
    gl = (country or "").lower()
    gl = "uk" if gl == "gb" else gl
    if gl in _COUNTRIES:
        body["gl"] = gl
    hl = (language or "").split("-")[0].lower()
    if hl in _LANGUAGES:
        body["hl"] = hl
    return body


def _post_json(url: str, token: str, body: dict[str, Any]) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    # RUN_URL is a fixed https URL, never user input.
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        return json.loads(response.read().decode())


def _datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def _leg(raw: dict[str, Any]) -> FlightLeg:
    code, _, number = str(raw.get("flight_number") or "").partition(" ")
    departure, arrival = raw["departure_airport"], raw["arrival_airport"]
    legroom = raw.get("legroom") or None
    return FlightLeg(
        airline=_parse_airline(code),
        flight_number=number,
        departure_airport=_parse_airport(departure["id"]),
        arrival_airport=_parse_airport(arrival["id"]),
        departure_datetime=_datetime(departure["time"]),
        arrival_datetime=_datetime(arrival["time"]),
        duration=raw["duration"],
        departure_airport_name=departure.get("name"),
        arrival_airport_name=arrival.get("name"),
        aircraft=raw.get("airplane"),
        legroom=legroom,
        overnight=bool(raw.get("overnight")),
        cabin=SeatType.ECONOMY,
    )


def _result(raw: dict[str, Any], currency: str) -> FlightResult:
    legs = [_leg(leg) for leg in raw["flights"]]
    layovers = [
        Layover(
            airport=_parse_airport(stop["id"]),
            duration=stop["duration"],
            overnight=bool(stop.get("overnight")),
            airport_name=stop.get("name"),
        )
        for stop in raw.get("layovers") or []
    ]
    emissions = raw.get("carbon_emissions") or {}
    return FlightResult(
        legs=legs,
        price=raw.get("price"),
        currency=currency,
        duration=raw.get("total_duration") or sum(leg.duration for leg in legs),
        stops=max(len(legs) - 1, 0),
        layovers=layovers or None,
        co2_emissions_g=emissions.get("this_flight"),
        co2_emissions_typical_g=emissions.get("typical_for_this_route"),
        co2_emissions_delta_pct=emissions.get("difference_percent"),
        primary_airline=legs[0].airline,
        primary_airline_name=raw["flights"][0].get("airline"),
    )


def parse_items(items: list[dict[str, Any]], currency: str) -> list[FlightResult]:
    """Turn the Actor's dataset items into :class:`FlightResult` rows.

    A row with an airport or airline fli doesn't know is skipped, as the
    direct decoder does.
    """
    flights: list[FlightResult] = []
    for item in items:
        for raw in (item.get("best_flights") or []) + (item.get("other_flights") or []):
            try:
                flights.append(_result(raw, currency))
            except (AttributeError, KeyError, TypeError, ValueError) as e:
                logger.debug("Skipping hosted flight row: %s: %s", type(e).__name__, e)
    return flights


def search_one_way(
    filters: FlightSearchFilters,
    token: str,
    *,
    currency: str | None = None,
    language: str | None = None,
    country: str | None = None,
) -> list[FlightResult]:
    """Run one hosted one-way search and return its rows (unfiltered).

    Raises:
        SearchClientError: The Apify call failed or returned no usable rows.

    """
    body = actor_input(filters, currency=currency, language=language, country=country)
    try:
        items = _post_json(RUN_URL, token, body)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise SearchClientError(f"Hosted fallback failed: {e}") from e
    if not isinstance(items, list):
        raise SearchClientError("Hosted fallback returned an unexpected response.")
    return parse_items(items, body["currency"])
