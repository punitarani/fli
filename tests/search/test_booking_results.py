"""Tests for parsing Google Flights booking results."""

import json
import urllib.parse
from datetime import datetime

import pytest

from fli.models import Airline, Airport, FlightLeg, FlightResult, PassengerInfo, SeatType
from fli.search import SearchFlights
from fli.search.booking_offers import parse_booking_results

SEK_TOKEN = (
    "CjRITUlGTEE5a3JNaXdBQXpKY1FCRy0tLS0tLS0tbG1iZnIxMUFBQUFBR25Mc253Smk0ZnlBEgZL"
    "TDEyMjYaCgjmExAAGgNTRUs4HHD2zgE="
)


class Response:
    def __init__(self, text: str):
        """Store response text for the booking-offer tests."""
        self.text = text

    def raise_for_status(self) -> None:
        return None


class RecordingClient:
    def __init__(self, text: str):
        """Record POST calls and return a fixed response body."""
        self.text = text
        self.calls: list[dict] = []

    def post(self, **kwargs):
        self.calls.append(kwargs)
        return Response(self.text)


def _make_wrb_line(payload: list) -> str:
    return json.dumps([["wrb.fr", None, json.dumps(payload, separators=(",", ":"))]])


def _make_offer(
    merchant_code: str,
    merchant_name: str,
    *,
    click_token: str,
    display_url: str,
    price: int,
    is_official: bool,
    offer_token: str,
) -> list:
    return [
        0,
        [[merchant_code, merchant_name, None, is_official]],
        None,
        [["KL", "1226"], ["KL", "1215"]],
        False,
        [
            display_url,
            None,
            ["https://www.google.com/travel/clk/f", [["u", click_token], ["hl", "en-US"]]],
        ],
        None,
        [[None, price], SEK_TOKEN],
        None,
        None,
        False,
        None,
        None,
        None,
        [[[None, [], 1]]],
        offer_token,
        [None, merchant_code, 0],
        None,
        True,
    ]


def test_parse_booking_results_extracts_clickthrough_offers():
    """Booking results should expose merchant clickthrough offers."""
    itinerary_payload = [
        [None, [[1, 2, 3], None, None, None, None, [[0]]], 0, "request", "session"],
        [None, None, None, None, None, []],
    ]
    offers_payload = [
        [None, [[1, 2, 3], None, None, None, None, [[4]]], 1, "request", "session"],
        [
            [
                _make_offer(
                    "KL",
                    "KLM",
                    click_token="ADowPOK_KLM",
                    display_url="www.klm.nl/...",
                    price=4781,
                    is_official=True,
                    offer_token="encoded-offer-klm",
                ),
                _make_offer(
                    "BOOKING",
                    "Booking.com",
                    click_token="ADowPOJ_BOOKING",
                    display_url="flights.booking.com/...",
                    price=4772,
                    is_official=False,
                    offer_token="encoded-offer-booking",
                ),
            ]
        ],
    ]
    raw_response = "\n".join(
        [
            ")]}'",
            "",
            str(len(_make_wrb_line(itinerary_payload))),
            _make_wrb_line(itinerary_payload),
            str(len(_make_wrb_line(offers_payload))),
            _make_wrb_line(offers_payload),
        ]
    )

    offers = parse_booking_results(raw_response)

    assert len(offers) == 2

    first = offers[0]
    assert first.merchant_code == "KL"
    assert first.merchant_name == "KLM"
    assert first.display_url == "www.klm.nl/..."
    assert first.price == 4781.0
    assert first.currency == "SEK"
    assert first.is_official is True
    assert first.flight_numbers == ["KL1226", "KL1215"]
    assert first.offer_token == "encoded-offer-klm"
    assert first.booking_url == "https://www.google.com/travel/clk/f?u=ADowPOK_KLM&hl=en-US"

    second = offers[1]
    assert second.merchant_code == "BOOKING"
    assert second.merchant_name == "Booking.com"
    assert second.display_url == "flights.booking.com/..."
    assert second.price == 4772.0
    assert second.currency == "SEK"
    assert second.is_official is False
    assert second.booking_url == "https://www.google.com/travel/clk/f?u=ADowPOJ_BOOKING&hl=en-US"


def test_parse_booking_results_ignores_duplicate_offer_nodes():
    """Duplicate booking rows should be deduplicated by merchant, price, and URL."""
    offer = _make_offer(
        "KL",
        "KLM",
        click_token="ADowPOK_KLM",
        display_url="www.klm.nl/...",
        price=4781,
        is_official=True,
        offer_token="encoded-offer-klm",
    )
    payload = [
        [None, [[1, 2, 3], None, None, None, None, [[4]]], 1, "request", "session"],
        [[offer, offer]],
    ]
    raw_response = "\n".join(
        [")]}'", "", str(len(_make_wrb_line(payload))), _make_wrb_line(payload)]
    )

    offers = parse_booking_results(raw_response)

    assert len(offers) == 1


def test_parse_booking_results_skips_non_booking_rows():
    """Rows without a Google clickthrough URL should not be treated as booking offers."""
    payload = [
        [None, [[1, 2, 3], None, None, None, None, [[4]]], 1, "request", "session"],
        [[[0, [["KL", "KLM", None, True]], None, [["KL", "1226"]], False, ["www.klm.nl/..."]]]],
    ]
    raw_response = "\n".join(
        [")]}'", "", str(len(_make_wrb_line(payload))), _make_wrb_line(payload)]
    )

    offers = parse_booking_results(raw_response)

    assert offers == []


def test_get_booking_offers_builds_booking_request_and_parses_response():
    """Booking offer lookup should post GetBookingResults and parse its offers."""
    offers_payload = [
        [None, [[1, 2, 3], None, None, None, None, [[4]]], 1, "request", "session"],
        [
            [
                _make_offer(
                    "KL",
                    "KLM",
                    click_token="ADowPOK_KLM",
                    display_url="www.klm.nl/...",
                    price=4781,
                    is_official=True,
                    offer_token="encoded-offer-klm",
                )
            ]
        ],
    ]
    raw_response = "\n".join(
        [")]}'", "", str(len(_make_wrb_line(offers_payload))), _make_wrb_line(offers_payload)]
    )

    flight = FlightResult(
        price=2534.0,
        currency="SEK",
        booking_token=SEK_TOKEN,
        duration=125,
        stops=0,
        legs=[
            FlightLeg(
                airline=Airline.KL,
                flight_number="1226",
                departure_airport=Airport.ARN,
                arrival_airport=Airport.AMS,
                departure_datetime=datetime(2026, 4, 23, 20, 55),
                arrival_datetime=datetime(2026, 4, 23, 23, 0),
                duration=125,
            )
        ],
    )
    search = SearchFlights()
    client = RecordingClient(raw_response)
    search.client = client

    offers = search.get_booking_offers(
        flight,
        passenger_info=PassengerInfo(adults=1),
        cabin_class=SeatType.ECONOMY,
    )

    assert len(offers) == 1
    assert offers[0].merchant_code == "KL"
    assert client.calls[0]["url"] == SearchFlights.BOOKING_URL

    encoded = client.calls[0]["data"].removeprefix("f.req=")
    wrapped = json.loads(urllib.parse.unquote(encoded))
    inner = json.loads(wrapped[1])

    assert inner[0] == [None, SEK_TOKEN]
    assert inner[1][13][0][8] == [["ARN", "2026-04-23", "AMS", None, "KL", "1226"]]


def test_get_booking_offers_uses_last_leg_token_for_round_trip():
    """Round-trip booking lookup should keep one selected flight per segment."""
    raw_response = "\n".join([")]}'", "", str(len(_make_wrb_line([]))), _make_wrb_line([])])

    outbound = FlightResult(
        price=2534.0,
        currency="SEK",
        booking_token="OUTBOUND_TOKEN",
        duration=125,
        stops=0,
        legs=[
            FlightLeg(
                airline=Airline.KL,
                flight_number="1226",
                departure_airport=Airport.ARN,
                arrival_airport=Airport.AMS,
                departure_datetime=datetime(2026, 4, 23, 20, 55),
                arrival_datetime=datetime(2026, 4, 23, 23, 0),
                duration=125,
            )
        ],
    )
    return_flight = FlightResult(
        price=2534.0,
        currency="SEK",
        booking_token="RETURN_TOKEN",
        duration=115,
        stops=0,
        legs=[
            FlightLeg(
                airline=Airline.KL,
                flight_number="1215",
                departure_airport=Airport.AMS,
                arrival_airport=Airport.ARN,
                departure_datetime=datetime(2026, 4, 25, 6, 55),
                arrival_datetime=datetime(2026, 4, 25, 8, 50),
                duration=115,
            )
        ],
    )

    search = SearchFlights()
    client = RecordingClient(raw_response)
    search.client = client
    search.get_booking_offers((outbound, return_flight))

    encoded = client.calls[0]["data"].removeprefix("f.req=")
    wrapped = json.loads(urllib.parse.unquote(encoded))
    inner = json.loads(wrapped[1])

    assert inner[0] == [None, "RETURN_TOKEN"]
    assert inner[1][13][0][8] == [["ARN", "2026-04-23", "AMS", None, "KL", "1226"]]
    assert inner[1][13][1][8] == [["AMS", "2026-04-25", "ARN", None, "KL", "1215"]]


def test_get_booking_offers_wraps_request_errors():
    """Booking lookup should add context to request failures."""

    class Client:
        def post(self, **kwargs):
            raise RuntimeError("boom")

    flight = FlightResult(
        price=2534.0,
        currency="SEK",
        booking_token=SEK_TOKEN,
        duration=125,
        stops=0,
        legs=[
            FlightLeg(
                airline=Airline.KL,
                flight_number="1226",
                departure_airport=Airport.ARN,
                arrival_airport=Airport.AMS,
                departure_datetime=datetime(2026, 4, 23, 20, 55),
                arrival_datetime=datetime(2026, 4, 23, 23, 0),
                duration=125,
            )
        ],
    )
    search = SearchFlights()
    search.client = Client()

    with pytest.raises(Exception) as exc_info:
        search.get_booking_offers(flight)

    assert str(exc_info.value) == "Booking offer lookup failed: boom"


def test_get_booking_offers_wraps_filter_build_errors():
    """Booking lookup should wrap validation errors from filter building."""
    flight = FlightResult(
        price=2534.0,
        currency="SEK",
        booking_token=SEK_TOKEN,
        duration=125,
        stops=0,
        legs=[],
    )
    search = SearchFlights()

    with pytest.raises(Exception) as exc_info:
        search.get_booking_offers(flight)

    assert (
        str(exc_info.value)
        == "Booking offer lookup failed: FlightResult must contain at least one leg"
    )
