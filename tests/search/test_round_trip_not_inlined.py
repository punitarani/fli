"""Offline tests for the round-trip-not-inlined warning.

On lower-traffic routes Google's search page often ships the round-trip board
with zero ``ds:1`` rows and fills it in afterwards through the signed
``GetShoppingResults`` RPC, even on dates when the one-way page for the same
outbound is full (measured 2026-11-28 on MAD-RIX). Without a diagnosis that
empty answer reads as "no flights". These tests pin the single one-way probe
that tells the two apart, and that it stays silent whenever it would not apply.
"""

from __future__ import annotations

import logging

from fli.models import Airline, PassengerInfo
from fli.search.flights import (
    ROUND_TRIP_NOT_INLINED_WARNING,
    SPARSE_PASSENGER_MIX_WARNING,
    SearchFlights,
)
from tests.search.test_sparse_passenger_warning import (
    _empty_page,
    _one_way_filters,
    _round_trip_filters,
    _row_page,
    _warnings,
)


def _client_serving_counted(monkeypatch, bodies: list[str]) -> tuple[SearchFlights, list[str]]:
    """Like ``_client_serving`` but also returns the list of requested URLs."""
    sf = SearchFlights()
    calls: list[str] = []

    def _fake_get(url, **kwargs):  # noqa: ANN001
        body = bodies[min(len(calls), len(bodies) - 1)]
        calls.append(url)
        return type("R", (), {"text": body, "raise_for_status": lambda self: None})()

    monkeypatch.setattr(sf.client, "get", _fake_get)
    return sf, calls


class TestRoundTripNotInlined:
    def test_empty_round_trip_with_flying_outbound_warns_once(self, monkeypatch, caplog):
        sf, calls = _client_serving_counted(monkeypatch, [_empty_page(), _row_page()])
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(_round_trip_filters(PassengerInfo(adults=1)))
        assert result is None
        warnings = _warnings(caplog)
        assert [w.getMessage() for w in warnings] == [ROUND_TRIP_NOT_INLINED_WARNING]
        assert sf.round_trip_not_inlined is True
        # Exactly one extra fetch: the one-way probe of the outbound segment
        assert len(calls) == 2

    def test_probe_is_a_one_way_search_of_the_outbound(self, monkeypatch):
        sf, calls = _client_serving_counted(monkeypatch, [_empty_page(), _row_page()])
        sf.search(_round_trip_filters(PassengerInfo(adults=1)))
        one_way, one_way_calls = _client_serving_counted(monkeypatch, [_row_page()])
        one_way.search(_one_way_filters(PassengerInfo(adults=1)))
        assert calls[1] == one_way_calls[0]

    def test_empty_round_trip_and_empty_outbound_stays_silent(self, monkeypatch, caplog):
        sf, calls = _client_serving_counted(monkeypatch, [_empty_page(), _empty_page()])
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            result = sf.search(_round_trip_filters(PassengerInfo(adults=1)))
        assert result is None
        assert _warnings(caplog) == []
        assert sf.round_trip_not_inlined is False
        assert len(calls) == 2

    def test_round_trip_with_results_never_probes(self, monkeypatch):
        sf, calls = _client_serving_counted(monkeypatch, [_row_page(), _row_page()])
        sf.search(_round_trip_filters(PassengerInfo(adults=1)), top_n=1)
        assert sf.round_trip_not_inlined is False
        # outbound page + one expansion page, and no probe
        assert len(calls) == 2

    def test_one_way_empty_never_probes(self, monkeypatch, caplog):
        sf, calls = _client_serving_counted(monkeypatch, [_empty_page()])
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            assert sf.search(_one_way_filters(PassengerInfo(adults=1))) is None
        assert sf.round_trip_not_inlined is False
        assert len(calls) == 1
        assert _warnings(caplog) == []

    def test_caller_filter_emptying_the_board_never_probes(self, monkeypatch):
        # Google inlined a DL row; the caller's own airline filter removed it.
        sf, calls = _client_serving_counted(monkeypatch, [_row_page("DL")])
        filters = _round_trip_filters(PassengerInfo(adults=1), airlines=[Airline.AA])
        assert sf.search(filters) is None
        assert sf.round_trip_not_inlined is False
        assert len(calls) == 1

    def test_sparse_passenger_mix_takes_precedence(self, monkeypatch, caplog):
        sf, calls = _client_serving_counted(monkeypatch, [_empty_page(), _row_page()])
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            sf.search(_round_trip_filters(PassengerInfo(adults=1, children=1)))
        assert [w.getMessage() for w in _warnings(caplog)] == [SPARSE_PASSENGER_MIX_WARNING]
        assert sf.round_trip_not_inlined is False
        assert len(calls) == 1

    def test_failed_probe_keeps_the_plain_empty_result(self, monkeypatch, caplog):
        sf, calls = _client_serving_counted(monkeypatch, [_empty_page(), "not a search page"])
        with caplog.at_level(logging.WARNING, logger="fli.search.flights"):
            assert sf.search(_round_trip_filters(PassengerInfo(adults=1))) is None
        assert sf.round_trip_not_inlined is False
        assert ROUND_TRIP_NOT_INLINED_WARNING not in [w.getMessage() for w in _warnings(caplog)]

    def test_flag_resets_on_next_search(self, monkeypatch):
        sf, _ = _client_serving_counted(monkeypatch, [_empty_page(), _row_page(), _row_page()])
        sf.search(_round_trip_filters(PassengerInfo(adults=1)))
        assert sf.round_trip_not_inlined is True
        sf.search(_one_way_filters(PassengerInfo(adults=1)))
        assert sf.round_trip_not_inlined is False
