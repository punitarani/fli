"""Offline tests for the sparse-passenger-mix warning on empty results.

Google's search-page transport inlines fewer (sometimes zero) rows for
parties with children or infants — the fares are priced client-side through
the gated RPC this transport cannot reach. An empty ``SearchFlights.search``
or ``SearchDates.search`` result for such a party used to be indistinguishable
from a route with no service at all; these tests pin the one warning each
call logs to explain the difference, and confirm it stays silent whenever it
would not apply.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

import pytest

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
)
from fli.models.google_flights.base import TripType
from fli.search import dates as dates_module
from fli.search.flights import SPARSE_PASSENGER_MIX_WARNING, SearchFlights
from tests.search._pages import as_search_page
from tests.search.test_parse_flights_data import _leg, _row


def _future(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _one_way_filters(passenger_info: PassengerInfo) -> FlightSearchFilters:
    return FlightSearchFilters(
        passenger_info=passenger_info,
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=_future(45),
            )
        ],
    )


def _round_trip_filters(passenger_info: PassengerInfo) -> FlightSearchFilters:
    return FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=passenger_info,
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=_future(45),
            ),
            FlightSegment(
                departure_airport=[[Airport.LAX, 0]],
                arrival_airport=[[Airport.JFK, 0]],
                travel_date=_future(52),
            ),
        ],
    )


def _page(rows: list) -> str:
    payload = [
        [None, None, None, None, "FAKE_SESSION"],
        None,
        [rows],
        None,
    ]
    return as_search_page(payload)


def _row_page() -> str:
    """Build a search page carrying exactly one parseable flight row."""
    return _page([_row(legs=[_leg(dep_iata="JFK", arr_iata="LAX")])])


def _empty_page() -> str:
    """Build a search page whose ``ds:1`` payload holds no rows."""
    return _page([])


def _client_serving(monkeypatch, bodies: list[str]) -> SearchFlights:
    """Return a ``SearchFlights`` whose ``client.get`` serves ``bodies`` in call order."""
    sf = SearchFlights()
    calls: list[str] = []

    def _fake_get(url, **kwargs):  # noqa: ANN001
        body = bodies[min(len(calls), len(bodies) - 1)]
        calls.append(url)
        return type("R", (), {"text": body, "raise_for_status": lambda self: None})()

    monkeypatch.setattr(sf.client, "get", _fake_get)
    return sf


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING]


class TestSparsePassengerMixWarningOneWay:
    def test_empty_with_child_warns_exactly_once(self, monkeypatch, caplog):
        sf = _client_serving(monkeypatch, [_empty_page()])
        filters = _one_way_filters(PassengerInfo(adults=1, children=1))
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(filters)
        assert result is None
        warnings = _warnings(caplog)
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        assert warnings[0].getMessage() == SPARSE_PASSENGER_MIX_WARNING

    def test_empty_with_lap_infant_warns_exactly_once(self, monkeypatch, caplog):
        sf = _client_serving(monkeypatch, [_empty_page()])
        filters = _one_way_filters(PassengerInfo(adults=1, infants_on_lap=1))
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(filters)
        assert result is None
        warnings = _warnings(caplog)
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        assert warnings[0].getMessage() == SPARSE_PASSENGER_MIX_WARNING

    def test_empty_with_seat_infant_warns_exactly_once(self, monkeypatch, caplog):
        sf = _client_serving(monkeypatch, [_empty_page()])
        filters = _one_way_filters(PassengerInfo(adults=1, infants_in_seat=1))
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(filters)
        assert result is None
        warnings = _warnings(caplog)
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"

    def test_empty_adults_only_does_not_warn(self, monkeypatch, caplog):
        sf = _client_serving(monkeypatch, [_empty_page()])
        filters = _one_way_filters(PassengerInfo(adults=2))
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(filters)
        assert result is None
        assert _warnings(caplog) == []

    def test_rows_with_child_does_not_warn(self, monkeypatch, caplog):
        sf = _client_serving(monkeypatch, [_row_page()])
        filters = _one_way_filters(PassengerInfo(adults=1, children=1))
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(filters)
        assert result is not None
        assert _warnings(caplog) == []


class TestSparsePassengerMixWarningRoundTrip:
    def test_empty_outbound_with_child_warns_exactly_once(self, monkeypatch, caplog):
        """The outbound page itself carries no rows — search stops right there."""
        sf = _client_serving(monkeypatch, [_empty_page()])
        filters = _round_trip_filters(PassengerInfo(adults=1, children=1))
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(filters)
        assert result is None
        warnings = _warnings(caplog)
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        assert warnings[0].getMessage() == SPARSE_PASSENGER_MIX_WARNING

    def test_empty_return_leg_with_child_warns_exactly_once(self, monkeypatch, caplog):
        """Outbound has rows but every expansion fetch for the return comes back empty.

        ``_fetch_flights`` runs twice here (outbound + one expansion candidate);
        the warning must still fire only once for the whole ``search()`` call.
        """
        sf = _client_serving(monkeypatch, [_row_page(), _empty_page()])
        filters = _round_trip_filters(PassengerInfo(adults=1, children=1))
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(filters)
        assert not result
        warnings = _warnings(caplog)
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        assert warnings[0].getMessage() == SPARSE_PASSENGER_MIX_WARNING

    def test_empty_round_trip_adults_only_does_not_warn(self, monkeypatch, caplog):
        sf = _client_serving(monkeypatch, [_row_page(), _empty_page()])
        filters = _round_trip_filters(PassengerInfo(adults=2))
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(filters)
        assert not result
        assert _warnings(caplog) == []

    def test_rows_on_both_legs_with_child_does_not_warn(self, monkeypatch, caplog):
        sf = _client_serving(monkeypatch, [_row_page(), _row_page()])
        filters = _round_trip_filters(PassengerInfo(adults=1, children=1))
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(filters)
        assert result
        assert _warnings(caplog) == []


@pytest.mark.parametrize(
    "info",
    [
        PassengerInfo(adults=1),
        PassengerInfo(adults=5),
    ],
)
def test_has_children_or_infants_false_for_adults_only(info):
    from fli.search.flights import _has_children_or_infants

    assert _has_children_or_infants(info) is False


@pytest.mark.parametrize(
    "info",
    [
        PassengerInfo(adults=1, children=1),
        PassengerInfo(adults=1, infants_on_lap=1),
        PassengerInfo(adults=1, infants_in_seat=1),
    ],
)
def test_has_children_or_infants_true(info):
    from fli.search.flights import _has_children_or_infants

    assert _has_children_or_infants(info) is True


# ---------------------------------------------------------------------------
# fli.search.dates.SearchDates
# ---------------------------------------------------------------------------

FIRST_DAY = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=30)


def _date_filters(days: int, passenger_info: PassengerInfo) -> DateSearchFilters:
    """One-way date filters spanning ``days`` dates starting at FIRST_DAY."""
    return DateSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=passenger_info,
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=FIRST_DAY.strftime("%Y-%m-%d"),
            )
        ],
        from_date=FIRST_DAY.strftime("%Y-%m-%d"),
        to_date=(FIRST_DAY + timedelta(days=days - 1)).strftime("%Y-%m-%d"),
    )


class _DateResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _CountingDateClient:
    """Serves ``body`` for every date request; thread-safe call counter."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls = 0
        self._lock = threading.Lock()

    def get(self, url: str, **kwargs):  # noqa: ANN001
        with self._lock:
            self.calls += 1
        return _DateResponse(self.body)


def _search_dates_with(client) -> dates_module.SearchDates:
    search = dates_module.SearchDates()
    search.client = client
    return search


def _date_warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING]


class TestSparsePassengerMixWarningDatesUnit:
    """Drives ``SearchDates._warn_if_sparse_passenger_mix`` directly.

    Mirrors how ``TestSweepCircuitBreaker`` in ``test_date_sweep.py`` drives
    ``_collect`` directly: the interesting states are a property of a fixed
    set of outcomes, not of racing a real sweep's concurrent fetches.
    """

    def test_no_result_no_failures_with_child_warns_once(self, caplog):
        outcomes = [dates_module._DateOutcome() for _ in range(3)]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            dates_module.SearchDates._warn_if_sparse_passenger_mix(
                outcomes, None, PassengerInfo(adults=1, children=1)
            )
        warnings = _date_warnings(caplog)
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        assert warnings[0].getMessage() == dates_module.SPARSE_PASSENGER_MIX_WARNING

    def test_no_result_no_failures_adults_only_does_not_warn(self, caplog):
        outcomes = [dates_module._DateOutcome() for _ in range(3)]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            dates_module.SearchDates._warn_if_sparse_passenger_mix(
                outcomes, None, PassengerInfo(adults=2)
            )
        assert _date_warnings(caplog) == []

    def test_no_result_with_a_failure_and_child_does_not_warn(self, caplog):
        """A failed date means ``_collect`` already explains the gap — see its docstring."""
        outcomes = [
            dates_module._DateOutcome(),
            dates_module._DateOutcome(),
            dates_module._DateOutcome(),
            dates_module._DateOutcome(failure="SearchConnectionError: transient"),
        ]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            dates_module.SearchDates._warn_if_sparse_passenger_mix(
                outcomes, None, PassengerInfo(adults=1, children=1)
            )
        assert _date_warnings(caplog) == []

    def test_a_result_with_child_does_not_warn(self, caplog):
        priced = dates_module.DatePrice(date=(FIRST_DAY,), price=150.0, currency="USD")
        outcomes = [dates_module._DateOutcome(price=priced)]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            dates_module.SearchDates._warn_if_sparse_passenger_mix(
                outcomes, [priced], PassengerInfo(adults=1, children=1)
            )
        assert _date_warnings(caplog) == []

    def test_one_failed_plus_three_empty_with_child_warns_exactly_once_total(self, caplog):
        """1 failed + 3 empty + child: exactly ONE warning overall, and it is #249's.

        Exercises ``_collect`` and ``_warn_if_sparse_passenger_mix`` together,
        in the same order ``SearchDates.search`` calls them, so the "cannot
        stack" contract between the two is pinned directly rather than only
        inferred from a full network sweep (which would also carry
        ``_price_one_date``'s own per-date failure warning and muddy the count).
        """
        outcomes = [
            dates_module._DateOutcome(),
            dates_module._DateOutcome(),
            dates_module._DateOutcome(),
            dates_module._DateOutcome(failure="SearchConnectionError: transient"),
        ]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            result = dates_module.SearchDates._collect(outcomes, 4, skipped=0)
            dates_module.SearchDates._warn_if_sparse_passenger_mix(
                outcomes, result, PassengerInfo(adults=1, children=1)
            )
        assert result is None
        warnings = _date_warnings(caplog)
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        # The one warning must be #249's minority-failure summary, not ours.
        assert warnings[0].getMessage() != dates_module.SPARSE_PASSENGER_MIX_WARNING
        assert "loaded" in warnings[0].getMessage()


class TestSparsePassengerMixWarningDatesIntegration:
    """End-to-end through ``SearchDates.search`` with a stubbed HTTP client."""

    def test_empty_sweep_with_child_warns_exactly_once(self, caplog):
        client = _CountingDateClient(_empty_page())
        filters = _date_filters(3, PassengerInfo(adults=1, children=1))
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            result = _search_dates_with(client).search(filters)
        assert result is None
        warnings = _date_warnings(caplog)
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        assert warnings[0].getMessage() == dates_module.SPARSE_PASSENGER_MIX_WARNING

    def test_empty_sweep_adults_only_does_not_warn(self, caplog):
        client = _CountingDateClient(_empty_page())
        filters = _date_filters(3, PassengerInfo(adults=2))
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            result = _search_dates_with(client).search(filters)
        assert result is None
        assert _date_warnings(caplog) == []

    def test_sweep_with_results_and_child_does_not_warn(self, caplog):
        client = _CountingDateClient(_row_page())
        filters = _date_filters(3, PassengerInfo(adults=1, children=1))
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            result = _search_dates_with(client).search(filters)
        assert result is not None
        assert _date_warnings(caplog) == []
