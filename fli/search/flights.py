"""Flight search implementation.

This module provides the core flight search functionality, interfacing directly
with Google Flights' API to find available flights and their details.
"""

import json
import logging
import urllib.parse
from copy import deepcopy
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
    FlightSearchFilters,
    Layover,
)
from fli.models.google_flights.base import TripType
from fli.search._wire import iter_wrb_chunks
from fli.search.client import get_client

logger = logging.getLogger(__name__)


class SearchFlights:
    """Flight search implementation using Google Flights' API.

    This class handles searching for specific flights with detailed filters,
    parsing the results into structured data models.
    """

    BASE_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetShoppingResults"
    BOOKING_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetBookingResults"
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }

    def __init__(self):
        """Initialize the search client for flight searches."""
        self.client = get_client()

    def search(
        self,
        filters: FlightSearchFilters,
        top_n: int = 5,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[FlightResult | tuple[FlightResult, ...]] | None:
        """Search for flights using the given FlightSearchFilters.

        Args:
            filters: Full flight search object including airports, dates, and preferences
            top_n: Number of flights to limit the return flight search to
            currency: Optional ISO 4217 currency code (e.g. ``"EUR"``) to bill prices in.
                When omitted, Google returns prices in the currency it picks from the
                request's IP / locale (usually USD).
            language: Optional BCP-47 language code (e.g. ``"en-GB"``) for the
                ``hl`` query parameter.
            country: Optional ISO 3166-1 alpha-2 country code (e.g. ``"GB"``) for
                the ``gl`` query parameter.

        Returns:
            List of FlightResult objects (one-way), tuples of FlightResult (round-trip
            or multi-city), or None if no results

        Raises:
            Exception: If the search fails or returns invalid data

        Note:
            Multi-city searches (TripType.MULTI_CITY) with distinct city pairs may
            time out due to limitations of the Google Flights API endpoint.  The
            endpoint reliably supports one-way and round-trip searches.

        """
        encoded_filters = filters.encode()
        url = _with_locale_params(self.BASE_URL, currency, language, country)

        try:
            response = self.client.post(
                url=url,
                data=f"f.req={encoded_filters}",
                impersonate="chrome",
                allow_redirects=True,
            )
            response.raise_for_status()

            parsed = json.loads(response.text.lstrip(")]}'"))[0][2]
            if not parsed:
                return None

            encoded_filters = json.loads(parsed)
            flights_data = [
                item
                for i in [2, 3]
                if isinstance(encoded_filters[i], list)
                for item in encoded_filters[i][0]
            ]
            flights = []
            for flight in flights_data:
                try:
                    flights.append(self._parse_flights_data(flight))
                except (AttributeError, KeyError, ValueError, TypeError) as e:
                    logger.debug("Skipping flight with unparseable data: %s", e)
                    continue

            if not flights:
                return None

            if filters.trip_type == TripType.ONE_WAY:
                return flights

            # For round-trip and multi-city, iteratively select each leg
            # and fetch the next leg's options with combined pricing.
            num_segments = len(filters.flight_segments)
            selected_count = sum(
                1 for s in filters.flight_segments if s.selected_flight is not None
            )

            # If all previous segments are selected, we're on the last leg
            if selected_count >= num_segments - 1:
                return flights

            # Select each flight option and fetch the next leg
            flight_combos = []
            for selected_flight in flights[:top_n]:
                next_filters = deepcopy(filters)
                next_filters.flight_segments[selected_count].selected_flight = selected_flight
                next_results = self.search(
                    next_filters,
                    top_n=top_n,
                    currency=currency,
                    language=language,
                    country=country,
                )
                if next_results is not None:
                    for next_result in next_results:
                        if isinstance(next_result, tuple):
                            flight_combos.append((selected_flight,) + next_result)
                        else:
                            flight_combos.append((selected_flight, next_result))

            return flight_combos

        except Exception as e:
            raise Exception(f"Search failed: {str(e)}") from e

    # ------------------------------------------------------------------
    # Booking options (vendor list)
    # ------------------------------------------------------------------

    def get_booking_options(
        self,
        flight: FlightResult | tuple[FlightResult, ...],
        filters: FlightSearchFilters,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
        booking_token: str | None = None,
    ) -> list[BookingOption]:
        """Fetch bookable fare options for a selected itinerary.

        ⚠️  KNOWN LIMITATION (May 2026): the GetBookingResults endpoint
        accepts a protobuf-encoded token at outer[0][1] that is *not* the
        same as the per-flight ``booking_token`` field surfaced on
        :class:`FlightResult`. Google's UI generates the booking-page
        token by concatenating the shopping session id from
        ``inner[0][4]`` with the selected airline+flight-number pair and
        currency metadata. Until that protobuf is reproduced client-side,
        live calls usually return Google's ``ErrorResponse`` (INVALID_ARGUMENT).

        The method still works perfectly when a valid token is supplied —
        e.g. captured from a browser session via the ``booking_token``
        argument, or via the :func:`fli.search._wire.iter_wrb_chunks` parser
        against a recorded response. The parser positions for the response
        side are stable; see ``tests/search/test_booking_options_live_fixture.py``.

        Args:
            flight: A single :class:`FlightResult` (one-way) or tuple of
                results (round-trip / multi-city) returned by :meth:`search`.
                Its legs populate the ``selected_flight`` slot of each filter
                segment so Google can match the itinerary.
            filters: The same :class:`FlightSearchFilters` used in the
                preceding ``search`` call. A copy is made internally; the
                caller's filters are not mutated.
            currency: Optional ISO 4217 currency code (``curr`` URL param).
            language: Optional BCP-47 language code (``hl`` URL param).
            country: Optional ISO 3166-1 alpha-2 country code (``gl`` URL param).
            booking_token: Optional explicit token to send at outer[0][1].
                Override for advanced use; defaults to ``flight.booking_token``.

        Returns:
            A list of :class:`BookingOption` objects. Empty list when Google
            returns no vendors *or* when the request is rejected.

        Raises:
            ValueError: If no token is available (neither argument nor flight).
            Exception: If the HTTP request itself fails (non-200, network).

        """
        results: list[FlightResult] = list(flight) if isinstance(flight, tuple) else [flight]
        if not results:
            raise ValueError("flight argument must be a FlightResult or non-empty tuple of them")
        token = booking_token or getattr(results[0], "booking_token", None)
        if not token:
            raise ValueError(
                "booking_token is required to fetch booking options; pass an "
                "explicit token or call SearchFlights.search to populate "
                "flight.booking_token first."
            )

        # Populate selected_flight on each segment so the encoded payload
        # carries the full itinerary the user picked.
        prepared = deepcopy(filters)
        segments = prepared.flight_segments
        if len(results) > len(segments):
            raise ValueError(
                f"flight has {len(results)} segments but filters has {len(segments)}"
            )
        for seg, res in zip(segments, results, strict=False):
            seg.selected_flight = res

        encoded_body = self._encode_booking_payload(token, prepared)
        url = _with_locale_params(self.BOOKING_URL, currency, language, country)

        try:
            response = self.client.post(
                url=url,
                data=f"f.req={encoded_body}",
                impersonate="chrome",
                allow_redirects=True,
            )
            response.raise_for_status()
        except Exception as e:
            raise Exception(f"Booking options request failed: {str(e)}") from e

        options: list[BookingOption] = []
        for chunk in iter_wrb_chunks(response.text):
            options.extend(self._parse_booking_chunk(chunk))
        return options

    @staticmethod
    def _encode_booking_payload(token: str, filters: FlightSearchFilters) -> str:
        """Build the URL-encoded ``f.req`` body for GetBookingResults."""
        formatted = filters.format()
        # The booking endpoint takes the same main-filter struct from
        # `format()[1]` (with selected_flight populated), plus the token at
        # outer[0] and a couple of trailing nulls. The other outer fields
        # (sort, show_all, ...) are ignored.
        main = formatted[1] if len(formatted) > 1 else None
        payload = [
            [None, token],
            main,
            None,
            0,
        ]
        wrapped = [None, json.dumps(payload, separators=(",", ":"))]
        return urllib.parse.quote(json.dumps(wrapped, separators=(",", ":")))

    @staticmethod
    def _parse_booking_chunk(chunk: Any) -> list[BookingOption]:
        """Extract booking-option rows from a single decoded wrb chunk."""
        if not isinstance(chunk, list):
            return []
        # Heuristic: the booking-options chunk has a top-level shape where
        # one of the elements is a list of `[idx, [[vendor]], None, [flights],
        # bool, [url_block], ...]` entries. We walk the chunk and harvest any
        # such rows.
        out: list[BookingOption] = []
        _walk_for_booking_rows(chunk, out)
        return out

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_flights_data(data: list) -> FlightResult:
        """Parse a single raw flight row into a structured FlightResult.

        The row layout is documented in ``.reverse-eng/notes/response_map.md``.
        """
        detail = data[0]
        price, currency = SearchFlights._parse_price_info(data)

        raw_legs = detail[2] or []
        legs = [SearchFlights._parse_leg(fl) for fl in raw_legs]
        layovers = SearchFlights._derive_layovers(legs, detail) if len(legs) > 1 else None

        emissions = SearchFlights._parse_emissions(detail)
        primary_airline = SearchFlights._safe_airline(_safe_get(detail, 0))
        primary_airline_name = None
        names_field = _safe_get(detail, 1)
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
            self_transfer=_as_bool(_safe_get(detail, 12)),
            mixed_cabin=_as_bool(_safe_get(data, 10)),
            primary_airline=primary_airline,
            primary_airline_name=primary_airline_name,
            booking_token=_as_str(_safe_get(data, 8)),
        )

    @staticmethod
    def _parse_leg(fl: list) -> FlightLeg:
        """Parse one leg array into a :class:`FlightLeg`."""
        airline_info = fl[22] or []
        airline = SearchFlights._safe_airline(_safe_get(airline_info, 0))
        flight_number = _as_str(_safe_get(airline_info, 1)) or ""

        # Operating carrier: when the marketing carrier and operator differ
        # Google fills airline_info[2] with the operating airline code.
        op_code = _safe_get(airline_info, 2)
        operating_airline = SearchFlights._safe_airline(op_code) if op_code else None

        amenities = SearchFlights._parse_amenities(_safe_get(fl, 12))
        aircraft = _as_str(_safe_get(fl, 17))
        legroom_short = _as_str(_safe_get(fl, 14))
        legroom_long = _as_str(_safe_get(fl, 30))
        overnight = _as_bool(_safe_get(fl, 19)) or False
        co2 = _safe_get(fl, 31)
        co2_emissions_g = co2 if isinstance(co2, int) and co2 >= 0 else None

        dep_airport = SearchFlights._parse_airport(fl[3])
        arr_airport = SearchFlights._parse_airport(fl[6])

        return FlightLeg(
            airline=airline,
            flight_number=flight_number,
            departure_airport=dep_airport,
            arrival_airport=arr_airport,
            departure_datetime=SearchFlights._parse_datetime(fl[20], fl[8]),
            arrival_datetime=SearchFlights._parse_datetime(fl[21], fl[10]),
            duration=fl[11],
            departure_airport_name=_as_str(_safe_get(fl, 4)),
            arrival_airport_name=_as_str(_safe_get(fl, 5)),
            operating_airline=operating_airline,
            operating_flight_number=None,
            aircraft=aircraft,
            legroom_short=legroom_short,
            legroom=legroom_long or legroom_short,
            amenities=amenities,
            overnight=overnight,
            co2_emissions_g=co2_emissions_g,
        )

    @staticmethod
    def _parse_amenities(slots: Any) -> Amenities | None:
        if not isinstance(slots, list) or not slots:
            return None
        # Slots positions inferred from comparison across many leg rows.
        # Tri-state: True / False / None.
        wifi = _as_bool(_safe_get(slots, 1))
        power = _as_bool(_safe_get(slots, 5))
        usb_power = _as_bool(_safe_get(slots, 9))
        on_demand_video = _as_bool(_safe_get(slots, 9))
        in_seat_video = None
        legroom_rating = _safe_get(slots, 11)
        if not isinstance(legroom_rating, int):
            legroom_rating = None
        if wifi is None and power is None and usb_power is None and legroom_rating is None:
            return None
        return Amenities(
            wifi=wifi,
            power=power,
            usb_power=usb_power,
            in_seat_video=in_seat_video,
            on_demand_video=on_demand_video,
            legroom_rating=legroom_rating,
        )

    @staticmethod
    def _parse_emissions(detail: list) -> dict[str, Any]:
        emissions_block = _safe_get(detail, 22)
        out: dict[str, Any] = {
            "this_g": None,
            "typical_g": None,
            "delta_pct": None,
            "tag": None,
        }
        if not isinstance(emissions_block, list):
            return out
        this_g = _safe_get(emissions_block, 7)
        typ_g = _safe_get(emissions_block, 8)
        delta = _safe_get(emissions_block, 3)
        tag_int = _safe_get(emissions_block, 11)

        if isinstance(this_g, int) and this_g >= 0:
            out["this_g"] = this_g
        if isinstance(typ_g, int) and typ_g >= 0:
            out["typical_g"] = typ_g
        if isinstance(delta, int):
            out["delta_pct"] = delta
        if tag_int in (1, 2, 3):
            out["tag"] = {1: "lower", 2: "typical", 3: "higher"}[tag_int]
        return out

    @staticmethod
    def _derive_layovers(legs: list[FlightLeg], detail: list) -> list[Layover]:
        """Compute layover objects from leg arrival/departure times.

        Falls back to Google's own ``detail[13]`` block when it exists for the
        layover airport name; durations are recomputed from leg timestamps for
        consistency.
        """
        if len(legs) < 2:
            return []
        layovers: list[Layover] = []
        # detail[13] is list of [mins, iata, iata, null, name, city, name, city] entries
        detail_block = _safe_get(detail, 13)
        if not isinstance(detail_block, list):
            detail_block = []
        for i in range(len(legs) - 1):
            prev = legs[i]
            nxt = legs[i + 1]
            wait = (nxt.departure_datetime - prev.arrival_datetime).total_seconds()
            delta_minutes = int(wait // 60)
            if delta_minutes < 0:
                delta_minutes = 0
            overnight = prev.arrival_datetime.date() != nxt.departure_datetime.date()
            change_of_airport = prev.arrival_airport != nxt.departure_airport
            layovers.append(
                Layover(
                    airport=prev.arrival_airport,
                    duration=delta_minutes,
                    overnight=overnight,
                    change_of_airport=change_of_airport,
                )
            )
        return layovers

    @staticmethod
    def _parse_price_info(data: list) -> tuple[float, str | None]:
        """Extract the numeric price and returned currency from raw flight data."""
        price_block = SearchFlights._get_price_block(data)
        price = 0.0
        currency = None
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

    @staticmethod
    def _parse_currency(data: list) -> str | None:
        """Extract the returned currency code from raw flight data."""
        try:
            price_block = SearchFlights._get_price_block(data)
            if price_block and len(price_block) > 1:
                return extract_currency_from_price_token(price_block[1])
        except (IndexError, TypeError):
            pass
        return None

    @staticmethod
    def _get_price_block(data: list) -> list | None:
        """Return the raw price block attached to a flight row."""
        try:
            if len(data) > 1 and isinstance(data[1], list):
                return data[1]
        except TypeError:
            pass
        return None

    @staticmethod
    def _parse_datetime(date_arr: list[int], time_arr: list[int]) -> datetime:
        """Convert date and time arrays to datetime.

        Args:
            date_arr: List of integers [year, month, day]
            time_arr: List of integers [hour, minute]

        Returns:
            Parsed datetime object

        Raises:
            ValueError: If arrays contain only None values

        """
        if not any(x is not None for x in date_arr) or not any(x is not None for x in time_arr):
            raise ValueError("Date and time arrays must contain at least one non-None value")

        return datetime(*(x or 0 for x in date_arr), *(x or 0 for x in time_arr))

    @staticmethod
    def _parse_airline(airline_code: str) -> Airline:
        """Convert airline code to Airline enum.

        Args:
            airline_code: Raw airline code from API

        Returns:
            Corresponding Airline enum value

        """
        if airline_code[0].isdigit():
            airline_code = f"_{airline_code}"
        return getattr(Airline, airline_code)

    @staticmethod
    def _safe_airline(code: Any) -> Airline | None:
        """Parse an airline code defensively; return None when invalid/missing."""
        if not isinstance(code, str) or not code:
            return None
        try:
            return SearchFlights._parse_airline(code)
        except (AttributeError, IndexError):
            return None

    @staticmethod
    def _parse_airport(airport_code: str) -> Airport:
        """Convert airport code to Airport enum.

        Args:
            airport_code: Raw airport code from API

        Returns:
            Corresponding Airport enum value

        """
        return getattr(Airport, airport_code)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _safe_get(seq: Any, idx: int) -> Any:
    if isinstance(seq, list) and 0 <= idx < len(seq):
        return seq[idx]
    return None


def _as_bool(v: Any) -> bool | None:
    return v if isinstance(v, bool) else None


def _as_str(v: Any) -> str | None:
    return v if isinstance(v, str) and v else None


def _walk_for_booking_rows(node: Any, out: list[BookingOption]) -> None:
    """Recursively look for booking-option entries inside a decoded chunk.

    A booking entry has the shape::

        [int_index, [[code, name, ?, is_direct], ...], None|list,
         [[al, fn], ...], bool, [url_block, ...], ...]

    plus optional trailing fields that include the per-fare price and the fare
    name when Google provides them. We're defensive about field positions
    because Google reshuffles them across A/B tests.
    """
    if isinstance(node, list):
        # Try to interpret this list as a booking row.
        opt = _try_parse_booking_row(node)
        if opt is not None:
            out.append(opt)
            return
        # Otherwise recurse into children.
        for child in node:
            _walk_for_booking_rows(child, out)


def _try_parse_booking_row(row: list) -> BookingOption | None:
    """Parse a single booking-option row using *positional* indices.

    Positions verified from a live GetBookingResults capture (May 2026):

    - [0]: index int
    - [1]: vendor list ``[[code, name, ?, is_airline_direct]]``
    - [3]: flights list ``[[airline_code, flight_no], ...]``
    - [5]: URL block ``[vendor_url_pattern, None, [google_click_url, ...]]``
    - [7]: price block ``[[None, price_int], currency_b64_token]`` (same
      shape as the price block on flight rows, so the same currency
      extractor works)
    - [14]: fare-code wrapper ``[[[None, [airline_code, FARE_CODE], 1]]]``
    - [21]: human-readable fare name at ``[3]``

    Returns None for anything that doesn't structurally look like a row.
    """
    if not isinstance(row, list) or len(row) < 8:
        return None
    if not isinstance(row[0], int):
        return None

    # Vendor block ----------------------------------------------------
    vendor_block = row[1]
    if not (isinstance(vendor_block, list) and vendor_block):
        return None
    first_vendor = vendor_block[0]
    if not (isinstance(first_vendor, list) and len(first_vendor) >= 2):
        return None
    if not isinstance(first_vendor[0], str) or not isinstance(first_vendor[1], str):
        return None
    is_direct = False
    if len(first_vendor) >= 4 and isinstance(first_vendor[3], bool):
        is_direct = first_vendor[3]

    # Flights covered ------------------------------------------------
    flights: list[tuple[str, str]] | None = None
    if isinstance(row[3], list):
        gathered: list[tuple[str, str]] = []
        for entry in row[3]:
            if (
                isinstance(entry, list)
                and len(entry) >= 2
                and isinstance(entry[0], str)
                and isinstance(entry[1], str)
            ):
                gathered.append((entry[0], entry[1]))
        flights = gathered or None

    # URLs -----------------------------------------------------------
    booking_url, google_click_url = _extract_booking_urls(row[5])

    # Price + currency from the canonical price block at row[7] -----
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

    # Fare name --------------------------------------------------------
    fare_name = _extract_fare_name(row)

    return BookingOption(
        vendor_code=first_vendor[0],
        vendor_name=first_vendor[1],
        is_airline_direct=is_direct,
        price=price,
        currency=currency,
        fare_name=fare_name,
        booking_url=booking_url,
        google_click_url=google_click_url,
        flights=flights,
    )


def _extract_booking_urls(block: Any) -> tuple[str | None, str | None]:
    """Return (vendor_url_pattern, google_click_url) from row[5]."""
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
    """Pick the human-readable fare name from row[21][3]; fall back to row[14]."""
    # Preferred: row[21][3] -> "Basic Economy" / "Main Cabin" / etc.
    if len(row) > 21 and isinstance(row[21], list) and len(row[21]) > 3:
        candidate = row[21][3]
        if isinstance(candidate, str) and candidate:
            return candidate
    # Fallback: row[14][0][0][1][1] which is the uppercase fare code.
    if len(row) > 14 and isinstance(row[14], list) and row[14]:
        try:
            label = row[14][0][0][1][1]
        except (IndexError, TypeError):
            label = None
        if isinstance(label, str) and label:
            return label
    return None


def _with_locale_params(
    url: str, currency: str | None, language: str | None, country: str | None
) -> str:
    """Append the optional ``curr``/``hl``/``gl`` query parameters to ``url``."""
    params: list[str] = []
    if currency:
        params.append(f"curr={currency.upper()}")
    if language:
        params.append(f"hl={language}")
    if country:
        params.append(f"gl={country.upper()}")
    if not params:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{'&'.join(params)}"
