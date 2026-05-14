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
    layovers = _derive_layovers(legs) if len(legs) > 1 else None

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
    if (
        wifi is None
        and power is None
        and on_demand_video is None
        and legroom_rating is None
    ):
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


def _derive_layovers(legs: list[FlightLeg]) -> list[Layover]:
    """Compute layovers from consecutive leg timestamps.

    Google also reports layovers in ``detail[13]`` with airport names, but
    we recompute the durations from the parsed leg datetimes for internal
    consistency (the leg times are already validated as ``datetime``).
    """
    layovers: list[Layover] = []
    for i in range(len(legs) - 1):
        prev = legs[i]
        nxt = legs[i + 1]
        wait_seconds = (nxt.departure_datetime - prev.arrival_datetime).total_seconds()
        delta_minutes = max(int(wait_seconds // 60), 0)
        layovers.append(
            Layover(
                airport=prev.arrival_airport,
                duration=delta_minutes,
                overnight=prev.arrival_datetime.date() != nxt.departure_datetime.date(),
                change_of_airport=prev.arrival_airport != nxt.departure_airport,
            )
        )
    return layovers


def _parse_price_info(row: list) -> tuple[float, str | None]:
    """Extract numeric price + ISO currency code from the price block."""
    price_block = _get_price_block(row)
    price = 0.0
    currency: str | None = None
    try:
        if price_block and price_block[0]:
            price = float(price_block[0][-1])
    except (IndexError, TypeError):
        pass
    try:
        if price_block and len(price_block) > 1:
            currency = extract_currency_from_price_token(price_block[1])
    except (IndexError, TypeError):
        pass
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


def _parse_airline(code: str) -> Airline:
    """Convert an airline IATA code into an :class:`Airline` enum value."""
    if code and code[0].isdigit():
        code = f"_{code}"
    return getattr(Airline, code)


def _safe_airline(code: Any) -> Airline | None:
    """Parse an airline code defensively; return None on missing/invalid."""
    if not isinstance(code, str) or not code:
        return None
    try:
        return _parse_airline(code)
    except (AttributeError, IndexError):
        return None


def _parse_airport(code: str) -> Airport:
    """Convert an airport IATA code into an :class:`Airport` enum value."""
    return getattr(Airport, code)


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
            label = None
        if isinstance(label, str) and label:
            return label
    return None
