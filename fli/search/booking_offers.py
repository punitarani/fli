"""Helpers for Google Flights booking-offer requests and parsing."""

import json
from urllib.parse import quote, urlencode

from fli.core import (
    extract_currency_from_price_token,
    parse_max_stops,
    parse_sort_by,
)
from fli.models import (
    BookingOffer,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
)
from fli.models.google_flights.base import TripType

BOOKING_FILTER_SEGMENTS_INDEX = 13
BOOKING_SELECTED_FLIGHTS_INDEX = 8
BOOKING_REQUEST_MODE = 0
CLICKTHROUGH_URL_MARKER = "google.com/travel/clk/"


def parse_booking_results(response_text: str) -> list[BookingOffer]:
    """Extract booking offers from a raw GetBookingResults response body."""
    offers: list[BookingOffer] = []
    seen: set[tuple[str, float, str | None]] = set()

    for payload in _iter_wrb_payloads(response_text):
        for node in _walk_lists(payload):
            offer = _parse_booking_offer(node)
            if offer is None:
                continue

            fingerprint = (offer.merchant_code, offer.price, offer.booking_url)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            offers.append(offer)

    return offers


def _iter_wrb_payloads(response_text: str):
    """Yield decoded wrb.fr payloads from a batched Google response."""
    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if not line or line == ")]}'" or line.isdigit() or not line.startswith("["):
            continue

        try:
            batch = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(batch, list):
            continue

        for entry in batch:
            if (
                isinstance(entry, list)
                and len(entry) > 2
                and entry[0] == "wrb.fr"
                and isinstance(entry[2], str)
            ):
                try:
                    yield json.loads(entry[2])
                except json.JSONDecodeError:
                    continue


def _walk_lists(node):
    """Yield each nested list in a payload tree."""
    if not isinstance(node, list):
        return

    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        for item in reversed(current):
            if isinstance(item, list):
                stack.append(item)


def _parse_booking_offer(node: list) -> BookingOffer | None:
    """Parse a booking offer node when the shape matches a known offer row."""
    if not _looks_like_booking_offer(node):
        return None

    merchant = node[1][0]
    display_info = node[5]
    price_block = node[7]

    price = _parse_offer_price(price_block)
    currency = _parse_offer_currency(price_block)
    booking_url = _build_click_url(display_info[2])
    flight_numbers = [
        f"{leg[0]}{leg[1]}"
        for leg in node[3]
        if isinstance(leg, list)
        and len(leg) > 1
        and isinstance(leg[0], str)
        and isinstance(leg[1], str)
    ]
    offer_token = node[15] if len(node) > 15 and isinstance(node[15], str) else None

    return BookingOffer(
        merchant_code=merchant[0],
        merchant_name=merchant[1],
        display_url=display_info[0] if isinstance(display_info[0], str) else None,
        booking_url=booking_url,
        price=price,
        currency=currency,
        is_official=(
            bool(merchant[3]) if len(merchant) > 3 and isinstance(merchant[3], bool) else False
        ),
        flight_numbers=flight_numbers,
        offer_token=offer_token,
    )


def _looks_like_booking_offer(node: list) -> bool:
    """Identify booking offer rows inside GetBookingResults payloads."""
    if not isinstance(node, list) or len(node) < 8:
        return False
    if not isinstance(node[0], int):
        return False
    if not isinstance(node[1], list) or not node[1] or not isinstance(node[1][0], list):
        return False
    merchant = node[1][0]
    if len(merchant) < 2 or not isinstance(merchant[0], str) or not isinstance(merchant[1], str):
        return False
    if not isinstance(node[3], list):
        return False
    if not isinstance(node[5], list) or len(node[5]) < 3:
        return False
    click_data = node[5][2]
    if (
        not isinstance(click_data, list)
        or not click_data
        or not isinstance(click_data[0], str)
        # Booking offers are identified by Google Flights clickthrough redirect URLs.
        or CLICKTHROUGH_URL_MARKER not in click_data[0]
    ):
        return False
    return isinstance(node[7], list) and bool(node[7]) and isinstance(node[7][0], list)


def _build_click_url(click_data: list) -> str | None:
    """Build a usable Google clickthrough URL from the encoded parameter list."""
    if not isinstance(click_data, list) or not click_data or not isinstance(click_data[0], str):
        return None

    base_url = click_data[0]
    params = []
    if len(click_data) > 1 and isinstance(click_data[1], list):
        for item in click_data[1]:
            if (
                isinstance(item, list)
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], str)
            ):
                params.append((item[0], item[1]))

    if not params:
        return base_url

    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode(params)}"


def _parse_offer_price(price_block: list) -> float:
    """Extract the numeric offer price from a GetBookingResults price block."""
    try:
        if price_block and price_block[0]:
            return float(price_block[0][-1])
    except (IndexError, TypeError, ValueError):
        pass
    return 0.0


def _parse_offer_currency(price_block: list) -> str | None:
    """Extract the returned offer currency from a GetBookingResults price block."""
    try:
        if price_block and len(price_block) > 1:
            return extract_currency_from_price_token(price_block[1])
    except (IndexError, TypeError):
        pass
    return None


def _build_selected_legs(flights: list[FlightResult]) -> list[list[str | None]]:
    """Build the selected-legs payload expected by GetBookingResults."""
    selected: list[list[str | None]] = []
    for flight in flights:
        for leg in flight.legs:
            selected.append(
                [
                    leg.departure_airport.name,
                    leg.departure_datetime.strftime("%Y-%m-%d"),
                    leg.arrival_airport.name,
                    None,
                    leg.airline.name,
                    leg.flight_number,
                ]
            )
    return selected


def build_booking_filter_block(
    *,
    flights: list[FlightResult],
    passenger_info: PassengerInfo,
    cabin_class: SeatType,
) -> list:
    """Build the filter block portion required by GetBookingResults."""
    segments = []
    for flight in flights:
        if not flight.legs:
            raise ValueError("FlightResult must contain at least one leg")
        first_leg = flight.legs[0]
        last_leg = flight.legs[-1]
        segments.append(
            FlightSegment(
                departure_airport=[[first_leg.departure_airport, 0]],
                arrival_airport=[[last_leg.arrival_airport, 0]],
                travel_date=first_leg.departure_datetime.strftime("%Y-%m-%d"),
                selected_flight=flight,
            )
        )

    trip_type = TripType.ONE_WAY
    if len(flights) == 2:
        if (
            flights[0].legs[0].departure_airport == flights[-1].legs[-1].arrival_airport
            and flights[0].legs[-1].arrival_airport == flights[1].legs[0].departure_airport
        ):
            trip_type = TripType.ROUND_TRIP
        else:
            trip_type = TripType.MULTI_CITY
    elif len(flights) > 2:
        trip_type = TripType.MULTI_CITY

    filters = FlightSearchFilters(
        trip_type=trip_type,
        passenger_info=passenger_info,
        flight_segments=segments,
        stops=parse_max_stops("ANY"),
        seat_type=cabin_class,
        airlines=None,
        sort_by=parse_sort_by("DEPARTURE_TIME"),
        exclude_basic_economy=False,
    )
    filter_block = filters.format()[1]

    # For one-way lookups, FlightSearchFilters.format() does not serialize the
    # selected flight into the per-segment block. GetBookingResults expects that
    # block to include the chosen legs at [13][segment][8], so inject it here.
    if len(flights) == 1:
        if (
            len(filter_block) <= BOOKING_FILTER_SEGMENTS_INDEX
            or not isinstance(filter_block[BOOKING_FILTER_SEGMENTS_INDEX], list)
            or not filter_block[BOOKING_FILTER_SEGMENTS_INDEX]
            or not isinstance(filter_block[BOOKING_FILTER_SEGMENTS_INDEX][0], list)
        ):
            raise ValueError("Unexpected booking filter block shape for selected-flight injection")
        segment_block = filter_block[BOOKING_FILTER_SEGMENTS_INDEX][0]
        while len(segment_block) <= BOOKING_SELECTED_FLIGHTS_INDEX:
            segment_block.append(None)
        segment_block[BOOKING_SELECTED_FLIGHTS_INDEX] = _build_selected_legs(flights)

    return filter_block


def build_booking_f_req(
    *,
    booking_token: str,
    filter_block: list,
) -> str:
    """Build the encoded f.req payload for GetBookingResults."""
    inner = [[None, booking_token], filter_block, None, BOOKING_REQUEST_MODE]
    wrapped = [None, json.dumps(inner, separators=(",", ":"))]
    return quote(json.dumps(wrapped, separators=(",", ":")))
