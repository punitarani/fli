"""Search transport built on Google Flights' public ``/travel/flights`` page.

Since 2026-08 the ``FlightsFrontendService`` RPC endpoints
(``GetShoppingResults``, ``GetCalendarGraph``) require an
``x-goog-batchexecute-bgr`` header that only the page's own JavaScript can
produce. The signature is bound to the exact request bytes, so a captured
token cannot be replayed against a different body — every plain HTTP client
gets HTTP 200 with a payload-less ``wrb.fr`` row carrying error 13.

The public search page is not gated that way. It serves the same result
payload inline, in an ``AF_initDataCallback`` blob keyed ``ds:1``, whose
elements ``[2]`` and ``[3]`` hold exactly the flight rows the RPC used to
return — so :mod:`fli.search._decoders` keeps working untouched. The page is
addressed by a ``tfs`` protobuf parameter instead of the ``f.req`` JSON
struct, which is what this module builds.

Scope note: ``tfs`` carries trip type, segments, stop limit, cabin,
passengers, alliances and layover restrictions. Filters with no known
``tfs`` field (airline include/exclude, price cap, duration, departure
window) are applied to the decoded results instead — see
:func:`apply_client_side_filters`. Anything that can be
neither encoded nor filtered after the fact is reported by
:func:`unsupported_filters` so the caller can warn rather than silently
return results that ignore it.

Multi-city is out of reach here entirely: the page inlines no rows for it,
so :func:`build_tfs` refuses those searches rather than returning the first
leg's one-way board.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from fli.models.google_flights.base import TripType
from fli.search._proto import LegSpec, encode_tfs_payload, encode_tfs_segment
from fli.search.exceptions import SearchUnsupportedError

if TYPE_CHECKING:
    from fli.models import FlightResult

logger = logging.getLogger(__name__)

PAGE_URL = "https://www.google.com/travel/flights"

# ``AF_initDataCallback({key: 'ds:1', hash: '..', data:[...], sideChannel: {}});``
_DS_BLOB = re.compile(r"AF_initDataCallback\((\{.*?\})\);", re.S)
_DS_KEY = re.compile(r"key:\s*'([^']+)'")
_DS_DATA = re.compile(r"data:(.*?), sideChannel", re.S)

# Passenger kinds, in the order Google's repeated field 8 expects them.
_PASSENGER_FIELDS = ("adults", "children", "infants_in_seat", "infants_on_lap")

# Filters with no ``tfs`` encoding and no reliable post-hoc equivalent —
# the decoded rows don't carry the data needed to apply them locally.
_UNSUPPORTED = (
    "emissions",
    "bags",
    "exclude_basic_economy",
)


def _iata(value: Any) -> str:
    """Return the bare IATA code for an ``Airport``/``Airline`` enum or string."""
    name = getattr(value, "name", None)
    return (name or str(value)).removeprefix("_")


def _legs_of(flight: FlightResult) -> list[LegSpec]:
    """Describe a chosen itinerary as the leg specs ``tfs`` pins it by."""
    return [
        LegSpec(
            origin=_iata(leg.departure_airport),
            dep_date=leg.departure_datetime.strftime("%Y-%m-%d"),
            dest=_iata(leg.arrival_airport),
            airline=_iata(leg.airline),
            flight_number=str(leg.flight_number),
        )
        for leg in flight.legs
    ]


def build_tfs(filters: Any, *, travel_dates: list[str] | None = None) -> str:
    """Build the ``tfs`` URL parameter for ``filters``.

    Args:
        filters: A ``FlightSearchFilters`` or ``DateSearchFilters``. Both
            carry ``trip_type``, ``passenger_info``, ``flight_segments``,
            ``stops`` and ``seat_type``, which is all this encoder reads.
        travel_dates: Optional per-segment date overrides, used by the date
            sweep to reprice one segment set across a range without
            deep-copying the whole filter object per day.

    Returns:
        The base64url ``tfs`` value, unpadded, as Google's own URLs carry it.

    Raises:
        SearchUnsupportedError: For multi-city trips, which this transport
            cannot serve at all.

    """
    # Field 19 is the trip type. Multi-city is 3, but sending 2 (one-way)
    # makes Google ignore every segment past the first and serve the first
    # leg's one-way board, which decodes cleanly into wrong results; sending
    # 3 renders the right board in a browser but inlines no flight rows —
    # multi-city is fetched client-side through the RPC gated since 2026-08.
    if filters.trip_type == TripType.MULTI_CITY:
        raise SearchUnsupportedError(
            "Multi-city search is not available through the search-page transport: "
            "Google loads those results client-side through the gated RPC, so the "
            "page carries no rows to read. Search each leg separately. "
            "See github.com/punitarani/fli#223."
        )

    stops = filters.stops.value
    passengers = [
        code
        for kind, code in zip(_PASSENGER_FIELDS, (1, 2, 3, 4), strict=False)
        for _ in range(getattr(filters.passenger_info, kind, 0))
    ]

    # Google reads alliances out of the same carrier lists as airline codes.
    carriers = [a.value for a in (getattr(filters, "alliances", None) or [])]
    carriers_exclude = [a.value for a in (getattr(filters, "alliances_exclude", None) or [])]
    layovers = getattr(filters, "layover_restrictions", None)

    segments = b""
    for index, segment in enumerate(filters.flight_segments):
        selected = segment.selected_flight
        segments += encode_tfs_segment(
            [_iata(entry[0]) for entry in segment.departure_airport],
            [_iata(entry[0]) for entry in segment.arrival_airport],
            travel_dates[index] if travel_dates else segment.travel_date,
            legs=_legs_of(selected) if selected is not None else (),
            # MaxStops.ANY (0) must leave the field out — writing 0 for it
            # would silently pin every search to non-stop.
            max_stops=stops - 1 if stops else None,
            carriers=carriers,
            carriers_exclude=carriers_exclude,
            layover_airports=[_iata(a) for a in (getattr(layovers, "airports", None) or [])],
            min_layover=getattr(layovers, "min_duration", None),
            max_layover=getattr(layovers, "max_duration", None),
        )

    return encode_tfs_payload(
        segments,
        is_one_way=filters.trip_type == TripType.ONE_WAY,
        passengers=passengers or [1],
        seat=filters.seat_type.value,
    )


def page_url(
    tfs: str,
    currency: str | None = None,
    language: str | None = None,
    country: str | None = None,
) -> str:
    """Build the search-page URL for a ``tfs`` value and locale."""
    params = [f"tfs={tfs}", f"hl={language or 'en'}", f"gl={country or 'US'}"]
    if currency:
        params.append(f"curr={currency}")
    return f"{PAGE_URL}?{'&'.join(params)}"


def extract_payload(html: str) -> Any | None:
    """Pull the ``ds:1`` payload out of a rendered search page.

    Returns the same structure the RPC used to hand back, so callers can
    keep reading ``payload[2]`` / ``payload[3]`` for flight rows.
    """
    for match in _DS_BLOB.finditer(html):
        blob = match.group(1)
        key = _DS_KEY.search(blob)
        if not key or key.group(1) != "ds:1":
            continue
        data = _DS_DATA.search(blob)
        if not data:
            continue
        try:
            return json.loads(data.group(1))
        except (ValueError, json.JSONDecodeError):
            logger.warning("ds:1 blob is not valid JSON", exc_info=True)
            return None
    return None


def unsupported_filters(filters: Any) -> list[str]:
    """Name the set filters this transport can neither encode nor emulate."""
    named = []
    for attr in _UNSUPPORTED:
        value = getattr(filters, attr, None)
        if value in (None, False, []):
            continue
        # Enum defaults (EmissionsFilter.ALL) are "unset" for our purposes.
        if getattr(value, "name", None) == "ALL":
            continue
        named.append(attr)
    return named


def apply_client_side_filters(flights: list[Any], filters: Any) -> list[Any]:
    """Apply the filters ``tfs`` has no field for, to already-decoded rows.

    Google would have applied these server-side and back-filled the result
    list, so a filtered search returns fewer options here than the old RPC
    did — but every option it does return honours the filter.
    """
    airlines = {_iata(a) for a in (getattr(filters, "airlines", None) or [])}
    excluded = {_iata(a) for a in (getattr(filters, "airlines_exclude", None) or [])}
    max_duration = getattr(filters, "max_duration", None)
    price_limit = getattr(filters, "price_limit", None)
    max_price = getattr(price_limit, "max_price", None)

    # These rows describe whichever segment the caller is still choosing, not
    # necessarily the outbound one. `_expand_multi_leg` pins a segment by
    # setting its `selected_flight` and re-fetches, so the flights coming back
    # belong to the first segment that is still unpinned. Filtering a return
    # leg against the outbound window drops valid evening returns and keeps
    # invalid ones, silently and in the caller's favour-looking direction.
    active = next(
        (
            index
            for index, segment in enumerate(filters.flight_segments)
            if getattr(segment, "selected_flight", None) is None
        ),
        max(0, len(filters.flight_segments) - 1),
    )
    segments = filters.flight_segments
    window = getattr(segments[active], "time_restrictions", None) if segments else None

    out = []
    for flight in flights:
        carriers = {_iata(leg.airline) for leg in flight.legs}
        if airlines and not carriers & airlines:
            continue
        if excluded and carriers & excluded:
            continue
        if max_duration is not None and flight.duration and flight.duration > max_duration:
            continue
        if max_price is not None and flight.price and flight.price > max_price:
            continue
        if not _within_window(flight, window):
            continue
        out.append(flight)
    return out


def _within_window(flight: Any, restrictions: Any) -> bool:
    """Check a flight's departure/arrival hours against a segment's window."""
    if restrictions is None:
        return True
    departure = flight.legs[0].departure_datetime.hour
    arrival = flight.legs[-1].arrival_datetime.hour
    checks = (
        (getattr(restrictions, "earliest_departure", None), departure, "min"),
        (getattr(restrictions, "latest_departure", None), departure, "max"),
        (getattr(restrictions, "earliest_arrival", None), arrival, "min"),
        (getattr(restrictions, "latest_arrival", None), arrival, "max"),
    )
    for bound, actual, kind in checks:
        if bound is None:
            continue
        if kind == "min" and actual < bound:
            return False
        if kind == "max" and actual > bound:
            return False
    return True
