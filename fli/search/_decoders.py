"""Pure response decoders for Google Flights' RPC payloads.

These functions take the already-deserialised inner-JSON value of a
``wrb.fr`` chunk (see :mod:`fli.search._wire`) and produce typed model
objects. They are intentionally I/O free so they can be exercised
deterministically against captured fixtures and from unit tests.

Position layouts live in ``.reverse-eng/notes/response_map.md`` (the
overall flight row) and ``.reverse-eng/notes/booking_results.md`` (the
booking-option row).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fli.core import extract_currency_from_price_token
from fli.models import (
    Airline,
    Airport,
    Amenities,
    BookingOption,
    FlightLeg,
    FlightResult,
    Layover,
)
from fli.search._helpers import as_bool, as_int, as_non_negative_int, as_str, safe_get

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flight result decoding
# ---------------------------------------------------------------------------


def parse_flight_row(row: list) -> FlightResult:
    """Decode a single flight row into a structured :class:`FlightResult`.

    Raises :class:`ValueError` / :class:`KeyError` / :class:`AttributeError`
    when the row is malformed; callers should treat those as "skip this row"
    rather than a hard failure (Google occasionally returns half-populated
    rows for advert / sponsor placements).
    """
    detail = row[0]
    price, currency = _parse_price_info(row)

    raw_legs = detail[2] or []
    legs = [_parse_leg(fl) for fl in raw_legs]
    layovers = _derive_layovers(legs, safe_get(detail, 13)) if len(legs) > 1 else None

    emissions = _parse_emissions(detail)
    primary_airline = _safe_airline(safe_get(detail, 0))
    primary_airline_name = None
    names_field = safe_get(detail, 1)
    if isinstance(names_field, list) and names_field:
        first = names_field[0]
        if isinstance(first, str):
            primary_airline_name = first

    return FlightResult(
        price=price,
        currency=currency,
        duration=detail[9],
        stops=max(len(legs) - 1, 0),
        legs=legs,
        layovers=layovers or None,
        co2_emissions_g=emissions["this_g"],
        co2_emissions_typical_g=emissions["typical_g"],
        co2_emissions_delta_pct=emissions["delta_pct"],
        emissions_tag=emissions["tag"],
        self_transfer=as_bool(safe_get(detail, 12)),
        mixed_cabin=as_bool(safe_get(row, 10)),
        primary_airline=primary_airline,
        primary_airline_name=primary_airline_name,
        booking_token=as_str(safe_get(row, 8)),
    )


def _parse_leg(fl: list) -> FlightLeg:
    airline_info = fl[22] or []
    airline = _safe_airline(safe_get(airline_info, 0))
    flight_number = as_str(safe_get(airline_info, 1)) or ""
    op_code = safe_get(airline_info, 2)
    operating_airline = _safe_airline(op_code) if op_code else None

    amenities = _parse_amenities(safe_get(fl, 12))
    aircraft = as_str(safe_get(fl, 17))
    legroom_short = as_str(safe_get(fl, 14))
    legroom_long = as_str(safe_get(fl, 30))
    overnight = as_bool(safe_get(fl, 19)) or False
    co2_emissions_g = as_non_negative_int(safe_get(fl, 31))

    return FlightLeg(
        airline=airline,
        flight_number=flight_number,
        departure_airport=_parse_airport(fl[3]),
        arrival_airport=_parse_airport(fl[6]),
        departure_datetime=_parse_datetime(fl[20], fl[8]),
        arrival_datetime=_parse_datetime(fl[21], fl[10]),
        duration=fl[11],
        departure_airport_name=as_str(safe_get(fl, 4)),
        arrival_airport_name=as_str(safe_get(fl, 5)),
        operating_airline=operating_airline,
        operating_flight_number=None,
        aircraft=aircraft,
        legroom_short=legroom_short,
        legroom=legroom_long or legroom_short,
        amenities=amenities,
        overnight=overnight,
        co2_emissions_g=co2_emissions_g,
    )


def _parse_amenities(slots: Any) -> Amenities | None:
    """Decode the 12-slot amenities array at ``leg[12]``.

    Confirmed slot mapping (live captures, May 2026):

    - slot 1 → wifi (bool|None)
    - slot 5 → power outlet (bool|None)
    - slot 9 → on-demand video (bool|None)
    - slot 11 → integer legroom rating (2 or 3 observed)

    Returns None when none of the known slots carry a usable value (avoids
    creating empty ``Amenities`` instances that would imply we know nothing
    about the leg).
    """
    if not isinstance(slots, list) or not slots:
        return None
    wifi = as_bool(safe_get(slots, 1))
    power = as_bool(safe_get(slots, 5))
    on_demand_video = as_bool(safe_get(slots, 9))
    legroom_rating = as_non_negative_int(safe_get(slots, 11))
    if wifi is None and power is None and on_demand_video is None and legroom_rating is None:
        return None
    return Amenities(
        wifi=wifi,
        power=power,
        usb_power=None,
        in_seat_video=None,
        on_demand_video=on_demand_video,
        legroom_rating=legroom_rating,
    )


def _parse_emissions(detail: list) -> dict[str, Any]:
    """Extract the four emissions metrics from ``detail[22]``."""
    emissions_block = safe_get(detail, 22)
    out: dict[str, Any] = {
        "this_g": None,
        "typical_g": None,
        "delta_pct": None,
        "tag": None,
    }
    if not isinstance(emissions_block, list):
        return out
    out["this_g"] = as_non_negative_int(safe_get(emissions_block, 7))
    out["typical_g"] = as_non_negative_int(safe_get(emissions_block, 8))
    out["delta_pct"] = as_int(safe_get(emissions_block, 3))
    tag_int = as_int(safe_get(emissions_block, 11))
    if tag_int in (1, 2, 3):
        out["tag"] = {1: "lower", 2: "typical", 3: "higher"}[tag_int]
    return out


def _derive_layovers(
    legs: list[FlightLeg],
    detail_block: Any = None,
) -> list[Layover]:
    """Compute layovers from consecutive leg timestamps.

    Durations / overnight / change-of-airport are recomputed from the
    parsed leg datetimes for internal consistency. When Google's
    ``detail[13]`` block is provided it carries airport name + city for
    each layover; those fields are merged in but never override the
    structurally-derived numbers.

    Shape of ``detail[13]`` (per layover entry, indices used here):
    ``[duration_mins, IATA, IATA, None, airport_name, city, ...]``
    """
    detail_entries: list = detail_block if isinstance(detail_block, list) else []
    layovers: list[Layover] = []
    for i in range(len(legs) - 1):
        prev = legs[i]
        nxt = legs[i + 1]
        wait_seconds = (nxt.departure_datetime - prev.arrival_datetime).total_seconds()
        delta_minutes = max(int(wait_seconds // 60), 0)

        airport_name: str | None = None
        city: str | None = None
        entry = detail_entries[i] if i < len(detail_entries) else None
        if isinstance(entry, list):
            airport_name = as_str(safe_get(entry, 4))
            city = as_str(safe_get(entry, 5))

        layovers.append(
            Layover(
                airport=prev.arrival_airport,
                duration=delta_minutes,
                overnight=prev.arrival_datetime.date() != nxt.departure_datetime.date(),
                change_of_airport=prev.arrival_airport != nxt.departure_airport,
                airport_name=airport_name,
                city=city,
            )
        )
    return layovers


def _parse_price_info(row: list) -> tuple[float | None, str | None]:
    """Extract numeric price + ISO currency code from the price block.

    Returns ``(None, currency)`` when the price head is an empty list
    (``[[], "<token>"]``) — Google's signal that it has not pre-computed
    a shopping-list price for this row. This happens routinely for
    premium-cabin round-trip itineraries, especially with multi-passenger
    configs (e.g. ``adults=2, children=1, seat_type=BUSINESS,
    trip_type=ROUND_TRIP``): Google declines to surface an aggregate
    "from $X" price and expects the user to drill into a specific
    outbound+return pair, then call ``GetBookingResults`` for real fares.
    The per-row booking token at ``row[8]`` is still populated, so
    callers can resolve real prices via
    :meth:`SearchFlights.get_booking_options`.

    Raises ``ValueError`` when the price block is genuinely malformed
    (non-numeric, wrong shape). Callers in :func:`parse_flight_row` will
    catch this and skip the row rather than ship a misleading ``$0.00``
    flight. Truly missing price blocks (sponsor placements with no
    ``row[1]``) trigger this too.
    """
    price_block = _get_price_block(row)
    if price_block is None:
        raise ValueError("price block missing — skip row")

    try:
        head = price_block[0]
        if not isinstance(head, list):
            raise ValueError("price head is not a list")
        if not head:
            # Empty head ([]) is Google's "no shopping-list price"
            # marker, not a malformed row. Surface the itinerary with
            # price=None so the caller can drill into GetBookingResults.
            price: float | None = None
        else:
            raw_price = head[-1]
            if isinstance(raw_price, bool) or not isinstance(raw_price, int | float):
                raise ValueError(f"price field is not numeric: {raw_price!r}")
            price = float(raw_price)
    except (IndexError, TypeError) as e:
        raise ValueError(f"malformed price block: {e}") from e

    currency: str | None = None
    if len(price_block) > 1:
        try:
            currency = extract_currency_from_price_token(price_block[1])
        except (IndexError, TypeError, ValueError) as e:
            # Currency is optional metadata; failure here is not fatal.
            logger.debug("Currency token decode failed: %s", e)
    return price, currency


def _get_price_block(row: list) -> list | None:
    """Return the price block (``row[1]``) when it has the expected shape."""
    block = safe_get(row, 1)
    return block if isinstance(block, list) else None


def _parse_datetime(date_arr: list[int], time_arr: list[int]) -> datetime:
    """Convert ``[y,m,d]`` + ``[h,m]`` arrays into a ``datetime``."""
    if not any(x is not None for x in date_arr) or not any(x is not None for x in time_arr):
        raise ValueError("Date and time arrays must contain at least one non-None value")
    return datetime(*(x or 0 for x in date_arr), *(x or 0 for x in time_arr))


# Airline / Airport enums are immutable so each code maps to a single
# member instance — cache the ``getattr`` walk so the parse hot path
# turns into a dict lookup. ``__members__`` is itself a dict, but going
# through ``getattr`` adds attribute-protocol overhead we don't need.
_AIRLINE_BY_CODE: dict[str, Airline] = {m.name: m for m in Airline}
_AIRPORT_BY_CODE: dict[str, Airport] = {m.name: m for m in Airport}


def _parse_airline(code: str) -> Airline:
    """Convert an airline IATA code into an :class:`Airline` enum value."""
    if code and code[0].isdigit():
        code = f"_{code}"
    try:
        return _AIRLINE_BY_CODE[code]
    except KeyError as e:
        raise AttributeError(code) from e


def _safe_airline(code: Any) -> Airline | None:
    """Parse an airline code defensively; return None on missing/invalid.

    A code that *is* a non-empty string but doesn't resolve to a known
    ``Airline`` enum value triggers a warning — it usually signals that
    Google has added a new IATA code we haven't catalogued yet. Known
    sentinels like ``"multi"`` (Google's codeshare placeholder) are
    accepted silently.
    """
    if not isinstance(code, str) or not code:
        return None
    if code in _AIRLINE_SENTINELS:
        return None
    try:
        return _parse_airline(code)
    except (AttributeError, IndexError):
        logger.warning(
            "Unknown airline IATA code %r — add to fli.models.Airline enum",
            code,
        )
        return None


# Pseudo-codes Google emits in place of a real IATA carrier identifier.
# Treat as "no single primary airline" rather than warning per row.
_AIRLINE_SENTINELS = frozenset({"multi"})


def _parse_airport(code: str) -> Airport:
    """Convert an airport IATA code into an :class:`Airport` enum value.

    Raises ``AttributeError`` for unknown codes — the caller in
    :func:`parse_flight_row` treats that as a "skip this row" signal,
    but we log a warning here so new airports surface in operator logs
    rather than vanishing silently from search results.
    """
    try:
        return _AIRPORT_BY_CODE[code]
    except KeyError as e:
        logger.warning(
            "Unknown airport IATA code %r — add to fli.models.Airport enum",
            code,
        )
        raise AttributeError(code) from e


# ---------------------------------------------------------------------------
# Booking option decoding
# ---------------------------------------------------------------------------


def parse_booking_chunk(chunk: Any) -> list[BookingOption]:
    """Walk a decoded ``wrb.fr`` chunk and yield every booking-option row."""
    options: list[BookingOption] = []
    _walk_for_booking_rows(chunk, options)
    return options


def _walk_for_booking_rows(node: Any, out: list[BookingOption]) -> None:
    """Recurse into ``node`` looking for booking-row-shaped lists."""
    if isinstance(node, list):
        opt = _try_parse_booking_row(node)
        if opt is not None:
            out.append(opt)
            return
        for child in node:
            _walk_for_booking_rows(child, out)


def _try_parse_booking_row(row: list) -> BookingOption | None:
    """Parse a booking row using positional indices.

    Positions verified from a live GetBookingResults capture (May 2026):

    - [0]: int index
    - [1]: vendor list ``[[code, name, ?, is_airline_direct]]``
    - [3]: flight list ``[[airline_code, flight_no], ...]``
    - [5]: URL block ``[vendor_url, None, [google_click_url, ...]]``
    - [7]: price block ``[[None, price], currency_token]`` (same shape as
      the flight-result price block — the same currency decoder works)
    - [14]: fare-code wrapper ``[[[None, [airline, FARE_CODE], 1]]]``
    - [21][3]: human-readable fare name

    Returns None when the shape doesn't match — false positives are
    unwanted because we walk every nested list looking for these rows.
    """
    if not isinstance(row, list) or len(row) < 8:
        return None
    if not isinstance(row[0], int):
        return None

    vendor_block = row[1]
    if not (isinstance(vendor_block, list) and vendor_block):
        return None
    first_vendor = vendor_block[0]
    if not (
        isinstance(first_vendor, list)
        and len(first_vendor) >= 2
        and isinstance(first_vendor[0], str)
        and isinstance(first_vendor[1], str)
    ):
        return None
    is_direct = (
        first_vendor[3] if len(first_vendor) >= 4 and isinstance(first_vendor[3], bool) else False
    )

    flights: list[tuple[str, str]] | None = None
    if isinstance(row[3], list):
        gathered: list[tuple[str, str]] = [
            (entry[0], entry[1])
            for entry in row[3]
            if isinstance(entry, list)
            and len(entry) >= 2
            and isinstance(entry[0], str)
            and isinstance(entry[1], str)
        ]
        if not gathered and row[3]:
            # row[3] was a non-empty list but no entry matched the shape —
            # likely a wire-format change. Log so the next debug session
            # has a breadcrumb; the booking option still parses with
            # ``flights=None`` (the model treats that as "unknown").
            logger.debug("Booking row[3] had %d entries but none matched shape", len(row[3]))
        flights = gathered or None

    booking_url, google_click_url = _extract_booking_urls(row[5])

    price: float | None = None
    currency: str | None = None
    if isinstance(row[7], list):
        pblock = row[7]
        if pblock and isinstance(pblock[0], list) and len(pblock[0]) >= 2:
            raw_price = pblock[0][-1]
            if isinstance(raw_price, int | float) and not isinstance(raw_price, bool):
                price = float(raw_price)
        if len(pblock) > 1 and isinstance(pblock[1], str):
            currency = extract_currency_from_price_token(pblock[1])

    return BookingOption(
        vendor_code=first_vendor[0],
        vendor_name=first_vendor[1],
        is_airline_direct=is_direct,
        price=price,
        currency=currency,
        fare_name=_extract_fare_name(row),
        booking_url=booking_url,
        google_click_url=google_click_url,
        flights=flights,
    )


def _extract_booking_urls(block: Any) -> tuple[str | None, str | None]:
    if not isinstance(block, list):
        return None, None
    vendor_url = block[0] if block and isinstance(block[0], str) else None
    google_click_url: str | None = None
    if len(block) > 2 and isinstance(block[2], list) and block[2]:
        candidate = block[2][0]
        if isinstance(candidate, str) and "/travel/clk" in candidate:
            google_click_url = candidate
    return vendor_url, google_click_url


def _extract_fare_name(row: list) -> str | None:
    """Prefer the human-readable name at ``row[21][3]``; fall back to row[14]."""
    if len(row) > 21 and isinstance(row[21], list) and len(row[21]) > 3:
        candidate = row[21][3]
        if isinstance(candidate, str) and candidate:
            return candidate
    if len(row) > 14 and isinstance(row[14], list) and row[14]:
        try:
            label = row[14][0][0][1][1]
        except (IndexError, TypeError):
            logger.debug("Fare-name fallback path at row[14] failed shape match")
            label = None
        if isinstance(label, str) and label:
            return label
    return None
