"""End-to-end parser test against a captured live response.

The fixture is a real ``GetBookingResults`` response captured from
www.google.com/travel/flights for JFK→LAX 2026-07-15 on American (round-trip
return 2026-07-19). The UI showed three fare cards: Basic Economy $347,
Main Cabin $457, Main Plus $649. This test locks in that exact behaviour
so wire-format changes don't silently break the parser.
"""

from pathlib import Path

import pytest

from fli.search._wire import iter_wrb_chunks
from fli.search.flights import SearchFlights

FIXTURE = Path(__file__).parent / "fixtures" / "booking_results_aa_jfk_lax.bin"


@pytest.fixture(scope="module")
def body() -> bytes:
    return FIXTURE.read_bytes()


def test_two_wrb_chunks(body: bytes) -> None:
    chunks = list(iter_wrb_chunks(body))
    assert len(chunks) == 2


def test_booking_options_extracted(body: bytes) -> None:
    chunks = list(iter_wrb_chunks(body))
    options = []
    for c in chunks:
        options.extend(SearchFlights._parse_booking_chunk(c))
    assert len(options) == 3, f"Expected 3 fare cards, got {len(options)}"


def test_fare_prices_match_ui(body: bytes) -> None:
    chunks = list(iter_wrb_chunks(body))
    options = []
    for c in chunks:
        options.extend(SearchFlights._parse_booking_chunk(c))
    prices = sorted(o.price for o in options if o.price is not None)
    assert prices == [347.0, 457.0, 649.0]


def test_all_options_are_airline_direct(body: bytes) -> None:
    chunks = list(iter_wrb_chunks(body))
    options = []
    for c in chunks:
        options.extend(SearchFlights._parse_booking_chunk(c))
    assert all(o.is_airline_direct for o in options)
    assert {o.vendor_code for o in options} == {"AA"}


def test_flights_attached_to_each_option(body: bytes) -> None:
    chunks = list(iter_wrb_chunks(body))
    options = []
    for c in chunks:
        options.extend(SearchFlights._parse_booking_chunk(c))
    for o in options:
        assert o.flights == [("AA", "171"), ("AA", "28")]


def test_google_click_url_present(body: bytes) -> None:
    chunks = list(iter_wrb_chunks(body))
    options = []
    for c in chunks:
        options.extend(SearchFlights._parse_booking_chunk(c))
    for o in options:
        assert o.google_click_url is not None
        assert "/travel/clk" in o.google_click_url
