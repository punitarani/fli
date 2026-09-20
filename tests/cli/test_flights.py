"""Tests for the flights CLI command."""

import json
from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from fli.cli.main import app
from fli.models import Airline, Airport, FlightLeg, FlightResult, SeatType
from fli.models.google_flights.base import TripType
from fli.search.exceptions import (
    SearchCertificateError,
    SearchClientError,
    SearchConnectionError,
    SearchHTTPError,
    SearchParseError,
    SearchTimeoutError,
)
from tests.search._pages import as_search_page
from tests.search.test_parse_flights_data import _leg, _row


@pytest.fixture
def runner():
    """Return a CliRunner instance."""
    return CliRunner()


def test_basic_flights_search(runner, mock_search_flights, mock_console):
    """Test basic flight search with required parameters."""
    result = runner.invoke(app, ["flights", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d")])
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_flights_with_time_filter(runner, mock_search_flights, mock_console):
    """Test flights search with time filter."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--time",
            "6-20",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_flights_with_passengers(runner, mock_search_flights, mock_console):
    """Test flights search passes adult passenger count into filters."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--passengers",
            "2",
        ],
    )
    assert result.exit_code == 0
    args, _ = mock_search_flights.search.call_args
    assert args[0].passenger_info.adults == 2


def test_flights_json_query_echoes_passengers(runner, mock_search_flights, mock_console):
    """JSON query echo includes requested adult passenger count."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--passengers",
            "3",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["query"]["passengers"] == 3


def test_flights_with_family_passenger_mix(runner, mock_search_flights, mock_console):
    """Test flights search passes the full passenger mix into filters."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--passengers",
            "2",
            "--children",
            "1",
            "--infants-in-seat",
            "1",
            "--infants-on-lap",
            "1",
        ],
    )
    assert result.exit_code == 0
    args, _ = mock_search_flights.search.call_args
    assert args[0].passenger_info.adults == 2
    assert args[0].passenger_info.children == 1
    assert args[0].passenger_info.infants_in_seat == 1
    assert args[0].passenger_info.infants_on_lap == 1
    # The same passenger mix must reach the per-flight booking deep link —
    # otherwise the family sees a family-priced result but a single-adult
    # booking page.
    mock_search_flights.build_flight_booking_url.assert_called()
    _, kwargs = mock_search_flights.build_flight_booking_url.call_args
    assert kwargs["passenger_info"].adults == 2
    assert kwargs["passenger_info"].children == 1
    assert kwargs["passenger_info"].infants_in_seat == 1
    assert kwargs["passenger_info"].infants_on_lap == 1


def test_flights_json_query_echoes_full_passenger_mix(runner, mock_search_flights, mock_console):
    """JSON query echo includes children/infants alongside adult passengers."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--passengers",
            "2",
            "--children",
            "1",
            "--infants-in-seat",
            "1",
            "--infants-on-lap",
            "1",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["query"]["passengers"] == 2
    assert payload["query"]["children"] == 1
    assert payload["query"]["infants_in_seat"] == 1
    assert payload["query"]["infants_on_lap"] == 1


def _field_8_codes(raw: bytes) -> list[int]:
    """Walk the top-level tfs message and collect every field-8 (passenger) code."""
    from fli.search._proto import _read_varint

    codes: list[int] = []
    offset = 0
    while offset < len(raw):
        tag, offset = _read_varint(raw, offset)
        field, wire = tag >> 3, tag & 0x7
        if wire == 0:
            value, offset = _read_varint(raw, offset)
            if field == 8:
                codes.append(value)
        elif wire == 2:
            length, offset = _read_varint(raw, offset)
            offset += length
        else:  # pragma: no cover - the encoder emits only wire types 0 and 2
            raise AssertionError(f"unexpected wire type {wire} at offset {offset}")
    return codes


def test_flights_json_booking_url_token_decodes_to_the_requested_mix(
    runner, mock_console, monkeypatch
):
    """One un-patched assertion: decode the real tfs token in --format json output.

    Every other CLI passenger-mix test uses ``mock_search_flights``, which
    replaces the whole ``SearchFlights`` instance (``build_flight_booking_url``
    included) and only checks the kwargs a mock recorded. Here only
    ``SearchFlights.search`` is stubbed, so ``build_flight_booking_url`` runs
    for real and produces an actual token — a bug in the token builder
    itself, not just in how the CLI calls it, would be caught here too.
    """
    import base64
    import urllib.parse

    from fli.search.flights import SearchFlights

    departure = datetime.now() + timedelta(days=30)
    flight = FlightResult(
        price=299.99,
        currency="USD",
        duration=360,
        stops=0,
        legs=[
            FlightLeg(
                airline=Airline.DL,
                flight_number="123",
                departure_airport=Airport.JFK,
                arrival_airport=Airport.LAX,
                departure_datetime=departure,
                arrival_datetime=departure + timedelta(hours=6),
                duration=360,
            )
        ],
    )
    monkeypatch.setattr(SearchFlights, "search", lambda self, *a, **k: [flight])

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            departure.strftime("%Y-%m-%d"),
            "--passengers",
            "2",
            "--children",
            "1",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    booking_url = payload["flights"][0]["booking_url"]

    tfs = urllib.parse.parse_qs(urllib.parse.urlparse(booking_url).query)["tfs"][0]
    pad = "=" * ((4 - len(tfs) % 4) % 4)
    raw = base64.urlsafe_b64decode(tfs + pad)
    assert _field_8_codes(raw) == [1, 1, 2]


def test_flights_invalid_passenger_mix_exits_nonzero_with_clean_message(
    runner, mock_search_flights, mock_console
):
    """A passenger mix Google Flights would reject fails cleanly, not with a pydantic dump."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--passengers",
            "1",
            "--infants-on-lap",
            "3",
        ],
    )
    assert result.exit_code == 1
    # One readable line, not pydantic's multi-line "1 validation error for..." dump.
    assert "validation error for" not in result.stdout.lower()
    assert "infants_on_lap" in result.stdout
    mock_search_flights.search.assert_not_called()


def test_flights_invalid_passenger_mix_json_error(runner, mock_search_flights, mock_console):
    """JSON mode surfaces the same passenger-mix error as a clean payload."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--passengers",
            "9",
            "--children",
            "1",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert "Total passengers must be between 1 and 9" in payload["error"]["message"]
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["retryable"] is False


def test_flights_invalid_lap_infant_mix_json_error(runner, mock_search_flights, mock_console):
    """1 adult + 2 lap infants (each needs its own adult) is also validation_error."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--passengers",
            "1",
            "--infants-on-lap",
            "2",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["retryable"] is False
    mock_search_flights.search.assert_not_called()


def test_flights_json_invalid_airport_code(runner, mock_search_flights, mock_console):
    """An unresolvable airport code reports validation_error, not a crash."""
    result = runner.invoke(
        app,
        ["flights", "ZZZZ", "LAX", datetime.now().strftime("%Y-%m-%d"), "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["retryable"] is False
    mock_search_flights.search.assert_not_called()


def test_flights_json_stubbed_blocked_page(runner, mock_search_flights, mock_console):
    """A SearchParseError (consent/blocked page) reports parse_error, not retryable as-is."""
    mock_search_flights.search.side_effect = SearchParseError(
        "the search page carried no ds:1 payload — Google may have changed the "
        "page shape, or served a consent/blocked page instead"
    )

    result = runner.invoke(
        app,
        ["flights", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d"), "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error"]["type"] == "parse_error"
    assert payload["error"]["retryable"] is False


@pytest.mark.parametrize(
    "exc, expected_type, expected_retryable",
    [
        # Released v0.9.0 CLI --format json values — must not move.
        pytest.param(SearchTimeoutError("slow"), "timeout", True, id="timeout"),
        pytest.param(SearchConnectionError("no route"), "connection_error", True, id="connection"),
        # certificate_error is a SearchConnectionError subclass but, unlike
        # its parent, deterministic — not retryable.
        pytest.param(
            SearchCertificateError("bad cert"), "certificate_error", False, id="certificate"
        ),
        pytest.param(SearchHTTPError("bad gw", status_code=502), "http_error", True, id="http-5xx"),
        pytest.param(
            SearchClientError("generic"), "search_error", False, id="generic-search-error"
        ),
        pytest.param(RuntimeError("bug"), "unexpected_error", False, id="unexpected"),
        # A bare ValueError used to be hardcoded to "search_error" by the
        # CLI's except (AttributeError, ValueError) block — now validation_error.
        pytest.param(ValueError("simulated bug"), "validation_error", False, id="bare-value-error"),
        # A bare AttributeError isn't a SearchClientError or an
        # input-validation failure, so the shared classifier calls it
        # unexpected_error (also previously hardcoded to "search_error").
        pytest.param(
            AttributeError("'NoneType' object has no attribute 'name'"),
            "unexpected_error",
            False,
            id="bare-attribute-error",
        ),
    ],
)
def test_flights_json_error_type_matches_shared_classifier(
    runner, mock_search_flights, mock_console, exc, expected_type, expected_retryable
):
    """Flights --format json's error_type/retryable match fli.core.errors.classify_error."""
    mock_search_flights.search.side_effect = exc

    result = runner.invoke(
        app,
        ["flights", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d"), "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error"]["type"] == expected_type
    assert payload["error"]["retryable"] is expected_retryable


def test_flights_with_airlines(runner, mock_search_flights, mock_console):
    """Repeated -a flags resolve to the matching Airline enums on the filter."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "-a",
            "DL",
            "-a",
            "UA",
        ],
    )
    assert result.exit_code == 0
    args, _ = mock_search_flights.search.call_args
    assert args[0].airlines == [Airline.DL, Airline.UA]


def test_flights_with_comma_separated_airlines(runner, mock_search_flights, mock_console):
    """Single -a flag with comma-joined codes splits into multiple airlines."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "-a",
            "DL,UA",
        ],
    )
    assert result.exit_code == 0
    args, _ = mock_search_flights.search.call_args
    assert args[0].airlines == [Airline.DL, Airline.UA]


def test_flights_json_query_echoes_split_airlines(runner, mock_search_flights, mock_console):
    """JSON query echo reflects the parsed, split airline list — not the raw input."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "-a",
            "DL,UA",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["query"]["airlines"] == ["DL", "UA"]


def test_flights_with_cabin_class(runner, mock_search_flights, mock_console):
    """Test flights search with cabin class."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--class",
            "BUSINESS",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()
    args, _ = mock_search_flights.search.call_args
    assert args[0].seat_type == SeatType.BUSINESS
    mock_search_flights.build_flight_booking_url.assert_called()
    _, kwargs = mock_search_flights.build_flight_booking_url.call_args
    assert kwargs["seat_type"] == SeatType.BUSINESS


def test_flights_with_stops(runner, mock_search_flights, mock_console):
    """Test flights search with stops filter."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--stops",
            "NON_STOP",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_flights_invalid_airport(runner, mock_search_flights, mock_console):
    """Test flights search with invalid airport code."""
    result = runner.invoke(
        app,
        ["flights", "XXX", "LAX", datetime.now().strftime("%Y-%m-%d")],
    )
    assert result.exit_code == 1
    assert "Error" in result.stdout


def test_flights_invalid_date(runner, mock_search_flights, mock_console):
    """Test flights search with invalid date format."""
    result = runner.invoke(app, ["flights", "JFK", "LAX", "2024-13-45"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_flights_no_results(runner, mock_search_flights, mock_console):
    """Test flights search with no results."""
    mock_search_flights.search.return_value = []

    result = runner.invoke(
        app,
        ["flights", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d")],
    )
    assert result.exit_code == 1
    assert "No flights found" in result.stdout
    assert "client-side" not in result.stdout


def test_flights_no_results_with_child_explains_the_sparsity(runner, mock_search_flights):
    """An empty result for a party with children/infants gets the extra hint.

    Google's search page inlines fewer (sometimes zero) rows for those
    parties — see SPARSE_PASSENGER_MIX_WARNING in fli.search.flights. The
    CLI reads search_client.sparse_passenger_mix rather than recomputing
    it, so the mock sets it the way the real library would for this party.
    """
    mock_search_flights.search.return_value = []
    mock_search_flights.sparse_passenger_mix = True

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--passengers",
            "2",
            "--children",
            "1",
        ],
    )
    assert result.exit_code == 1
    assert "No flights found" in result.stdout
    assert "client-side" in result.stdout


def test_flights_no_results_with_infant_explains_the_sparsity(runner, mock_search_flights):
    mock_search_flights.search.return_value = []
    mock_search_flights.sparse_passenger_mix = True

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--infants-on-lap",
            "1",
        ],
    )
    assert result.exit_code == 1
    assert "client-side" in result.stdout


class TestFlightsNoteTracksGoogleNotTheCallersFilter:
    """End-to-end (stubbed page, real ``SearchFlights.search``) — mirrors the MCP-level check.

    A page that genuinely carries no rows still gets the hint; a page that
    carries a row the caller's own airline filter then removes does not —
    that emptiness is the filter's doing, not Google's.
    """

    def _page(self, rows: list) -> str:
        payload = [[None, None, None, None, "FAKE_SESSION"], None, [rows], None]
        return as_search_page(payload)

    def _stub_get(self, monkeypatch, body: str) -> None:
        def _fake_get(self, url, **kwargs):  # noqa: ANN001
            return type("R", (), {"text": body, "raise_for_status": lambda self: None})()

        monkeypatch.setattr("fli.search.client.Client.get", _fake_get)

    def test_genuinely_empty_page_prints_the_hint(self, runner, monkeypatch):
        self._stub_get(monkeypatch, self._page([]))
        result = runner.invoke(
            app,
            ["flights", "JFK", "LHR", datetime.now().strftime("%Y-%m-%d"), "--children", "1"],
        )
        assert result.exit_code == 1
        assert "No flights found" in result.stdout
        assert "client-side" in result.stdout

    def test_rows_filtered_out_by_airline_prints_no_hint(self, runner, monkeypatch):
        row = _row(legs=[_leg(dep_iata="JFK", arr_iata="LHR", airline_code="DL")])
        self._stub_get(monkeypatch, self._page([row]))
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LHR",
                datetime.now().strftime("%Y-%m-%d"),
                "--children",
                "1",
                "--airlines",
                "AA",
            ],
        )
        assert result.exit_code == 1
        assert "No flights found" in result.stdout
        assert "client-side" not in result.stdout


def test_basic_round_trip_flights(runner, mock_search_flights, mock_console):
    """Test basic round-trip flight search."""
    outbound_date = datetime.now().strftime("%Y-%m-%d")
    return_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            outbound_date,
            "--return",
            return_date,
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_round_trip_with_filters(runner, mock_search_flights, mock_console):
    """Test round-trip flights search with additional filters."""
    outbound_date = datetime.now().strftime("%Y-%m-%d")
    return_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            outbound_date,
            "--return",
            return_date,
            "--class",
            "BUSINESS",
            "--stops",
            "NON_STOP",
            "-a",
            "DL",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()
    args, kwargs = mock_search_flights.search.call_args
    assert args[0].trip_type == TripType.ROUND_TRIP


def test_round_trip_invalid_dates(runner, mock_search_flights, mock_console):
    """Test round-trip flights search with return date before outbound date."""
    outbound_date = datetime.now().strftime("%Y-%m-%d")
    return_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            outbound_date,
            "--return",
            return_date,
        ],
    )
    assert result.exit_code == 1
    assert "Error" in result.stdout


def test_flights_json_output(runner, mock_search_flights, mock_console):
    """Test flights search with JSON output."""
    result = runner.invoke(
        app,
        ["flights", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d"), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data_source"] == "google_flights"
    assert payload["search_type"] == "flights"
    assert payload["trip_type"] == "ONE_WAY"
    assert payload["count"] == 2
    assert payload["query"]["origin"] == "JFK"
    assert payload["query"]["destination"] == "LAX"
    assert payload["flights"][0]["price"] == 299.99
    assert payload["flights"][0]["currency"] == "USD"
    assert payload["flights"][0]["legs"][0]["departure_airport"]["code"] == "JFK"
    assert payload["flights"][0]["legs"][0]["arrival_airport"]["code"] == "LAX"


def test_flights_json_round_trip_output(runner, mock_search_flights, mock_console):
    """Test round-trip flights JSON output preserves outbound and return sections."""
    now = datetime.now()
    mock_search_flights.search.return_value = [
        (
            FlightResult(
                price=599.98,
                duration=180,
                stops=0,
                legs=[
                    FlightLeg(
                        airline=Airline.DL,
                        flight_number="DL123",
                        departure_airport=Airport.JFK,
                        arrival_airport=Airport.LAX,
                        departure_datetime=now,
                        arrival_datetime=now + timedelta(hours=3),
                        duration=180,
                    )
                ],
            ),
            FlightResult(
                price=599.98,
                duration=200,
                stops=1,
                legs=[
                    FlightLeg(
                        airline=Airline.DL,
                        flight_number="DL456",
                        departure_airport=Airport.LAX,
                        arrival_airport=Airport.JFK,
                        departure_datetime=now + timedelta(days=7),
                        arrival_datetime=now + timedelta(days=7, hours=4),
                        duration=200,
                    )
                ],
            ),
        )
    ]

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            now.strftime("%Y-%m-%d"),
            "--return",
            (now + timedelta(days=7)).strftime("%Y-%m-%d"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["trip_type"] == "ROUND_TRIP"
    assert payload["count"] == 1
    assert payload["flights"][0]["price"] == 599.98
    assert payload["flights"][0]["duration"] == 380
    assert payload["flights"][0]["stops"] == 1
    assert payload["flights"][0]["outbound"]["legs"][0]["flight_number"] == "DL123"
    assert payload["flights"][0]["return"]["legs"][0]["flight_number"] == "DL456"


def test_flights_json_invalid_date(runner, mock_search_flights, mock_console):
    """Test flights JSON output for invalid dates."""
    result = runner.invoke(
        app,
        ["flights", "JFK", "LAX", "2024-13-45", "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["search_type"] == "flights"
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["retryable"] is False
    assert "YYYY-MM-DD" in payload["error"]["message"]


def test_flights_json_no_results(runner, mock_search_flights, mock_console):
    """Test flights JSON output when no results are found."""
    mock_search_flights.search.return_value = []

    result = runner.invoke(
        app,
        ["flights", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d"), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["count"] == 0
    assert payload["flights"] == []
    assert "note" not in payload


def test_flights_json_no_results_with_child_carries_a_note(
    runner, mock_search_flights, mock_console
):
    """The JSON empty payload gets the same explanation as a `note` key."""
    mock_search_flights.search.return_value = []
    mock_search_flights.sparse_passenger_mix = True

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--passengers",
            "2",
            "--children",
            "1",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["count"] == 0
    assert "client-side" in payload["note"]


def test_given_comma_separated_origin_list_then_returns_flights_from_all(
    runner, mock_search_flights, mock_console
):
    """Comma-separated origin passes multiple airports to the search segment."""
    result = runner.invoke(
        app,
        ["flights", "JFK,LGA", "LAX", datetime.now().strftime("%Y-%m-%d")],
    )
    assert result.exit_code == 0
    args, _ = mock_search_flights.search.call_args
    departure_airports = [apt for apt, _ in args[0].flight_segments[0].departure_airport]
    assert Airport.JFK in departure_airports
    assert Airport.LGA in departure_airports


def test_given_comma_separated_destination_list_then_returns_flights_to_all(
    runner, mock_search_flights, mock_console
):
    """Comma-separated destination passes multiple airports to the search segment."""
    result = runner.invoke(
        app,
        ["flights", "JFK", "LHR,CDG", datetime.now().strftime("%Y-%m-%d")],
    )
    assert result.exit_code == 0
    args, _ = mock_search_flights.search.call_args
    arrival_airports = [apt for apt, _ in args[0].flight_segments[0].arrival_airport]
    assert Airport.LHR in arrival_airports
    assert Airport.CDG in arrival_airports


@pytest.mark.parametrize("bad_origin", [",", ",,", " , "])
def test_flights_separator_only_origin_is_a_clean_error(
    runner, mock_search_flights, mock_console, bad_origin
):
    """An origin made only of separators gets a clear parse error.

    Previously the empty airport list reached the models and surfaced as a raw
    pydantic validation dump.
    """
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    result = runner.invoke(app, ["flights", bad_origin, "LAX", tomorrow])
    assert result.exit_code != 0
    assert "No valid airport codes" in result.output
    assert "pydantic" not in result.output
    mock_search_flights.search.assert_not_called()
