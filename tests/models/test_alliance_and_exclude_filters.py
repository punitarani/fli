"""Tests for Alliance enum + airlines_exclude/alliances/alliances_exclude.

These tests exercise the new filter shapes added in May 2026 after
empirically discovering that:

- ``segment[4]`` (the existing include list) accepts a mix of airline IATA
  codes AND alliance identifier strings (``"ONEWORLD"``, ``"SKYTEAM"``,
  ``"STAR_ALLIANCE"``).
- ``segment[5]`` (previously "unknown") is an exclude list of the same
  shape.
"""

from datetime import datetime, timedelta
import json

from fli.models import (
    Airline,
    Airport,
    Alliance,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    LayoverRestrictions,
    PassengerInfo,
    TripType,
)


def _future_date(days_ahead: int = 30) -> str:
    return (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def _basic_segment(date: str | None = None) -> FlightSegment:
    return FlightSegment(
        departure_airport=[[Airport.JFK, 0]],
        arrival_airport=[[Airport.LAX, 0]],
        travel_date=date or _future_date(),
    )


def _basic_filters(**overrides) -> FlightSearchFilters:
    return FlightSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[_basic_segment()],
        **overrides,
    )


def _segment_from_filters(filters) -> list:
    """Pull the encoded segment array out of a filters object."""
    return filters.format()[1][13][0]


class TestAllianceEnum:
    def test_values_match_googles_required_spelling(self):
        # Verified empirically — Google rejects "Star Alliance" with a space.
        assert Alliance.ONEWORLD.value == "ONEWORLD"
        assert Alliance.SKYTEAM.value == "SKYTEAM"
        assert Alliance.STAR_ALLIANCE.value == "STAR_ALLIANCE"

    def test_three_alliances_only(self):
        # Google Flights only filters by these three; if a fourth ever shows
        # up, the enum will need updating.
        assert {a.value for a in Alliance} == {"ONEWORLD", "SKYTEAM", "STAR_ALLIANCE"}


class TestAirlinesIncludeMixedWithAlliances:
    def test_only_alliance(self):
        filters = _basic_filters(alliances=[Alliance.ONEWORLD])
        seg = _segment_from_filters(filters)
        assert seg[4] == ["ONEWORLD"]

    def test_alliance_and_airline_together(self):
        # Both lists feed into segment[4] — alliance values come after
        # sorted airline codes.
        filters = _basic_filters(airlines=[Airline.DL], alliances=[Alliance.ONEWORLD])
        seg = _segment_from_filters(filters)
        assert seg[4] == ["DL", "ONEWORLD"]

    def test_multiple_alliances_sorted(self):
        filters = _basic_filters(alliances=[Alliance.STAR_ALLIANCE, Alliance.ONEWORLD])
        seg = _segment_from_filters(filters)
        # Alphabetical sort for deterministic encoding.
        assert seg[4] == ["ONEWORLD", "STAR_ALLIANCE"]

    def test_no_alliance_keeps_existing_airlines_only(self):
        filters = _basic_filters(airlines=[Airline.DL])
        seg = _segment_from_filters(filters)
        assert seg[4] == ["DL"]

    def test_empty_yields_null_at_position_4(self):
        filters = _basic_filters()
        seg = _segment_from_filters(filters)
        assert seg[4] is None


class TestAirlinesExcludeAndAlliancesExclude:
    def test_exclude_position_is_5(self):
        filters = _basic_filters(airlines_exclude=[Airline.DL])
        seg = _segment_from_filters(filters)
        assert seg[5] == ["DL"]

    def test_alliance_exclude_at_position_5(self):
        filters = _basic_filters(alliances_exclude=[Alliance.SKYTEAM])
        seg = _segment_from_filters(filters)
        assert seg[5] == ["SKYTEAM"]

    def test_mixed_exclude(self):
        filters = _basic_filters(
            airlines_exclude=[Airline.DL, Airline.B6],
            alliances_exclude=[Alliance.STAR_ALLIANCE],
        )
        seg = _segment_from_filters(filters)
        # Airlines come first (sorted by .value — the full airline name,
        # matching the existing behaviour of the include list), then
        # alliance values (sorted alphabetically). Delta Air Lines < JetBlue
        # so DL precedes B6 in the output.
        assert set(seg[5]) == {"B6", "DL", "STAR_ALLIANCE"}
        # Alliance value sits at the end of the list (after the airline codes).
        assert seg[5][-1] == "STAR_ALLIANCE"
        assert seg[5][:2] == ["DL", "B6"]

    def test_include_and_exclude_coexist(self):
        filters = _basic_filters(
            airlines=[Airline.DL],
            airlines_exclude=[Airline.B6],
        )
        seg = _segment_from_filters(filters)
        assert seg[4] == ["DL"]
        assert seg[5] == ["B6"]

    def test_empty_exclude_yields_null(self):
        filters = _basic_filters()
        seg = _segment_from_filters(filters)
        assert seg[5] is None


class TestMinLayoverDurationEncoding:
    def test_min_at_position_11_max_at_position_12(self):
        filters = _basic_filters(
            layover_restrictions=LayoverRestrictions(min_duration=60, max_duration=180),
        )
        seg = _segment_from_filters(filters)
        assert seg[11] == 60
        assert seg[12] == 180

    def test_only_min_set(self):
        filters = _basic_filters(
            layover_restrictions=LayoverRestrictions(min_duration=90),
        )
        seg = _segment_from_filters(filters)
        assert seg[11] == 90
        assert seg[12] is None

    def test_only_max_set(self):
        # Backwards compatible with the previous library API which only had max.
        filters = _basic_filters(
            layover_restrictions=LayoverRestrictions(max_duration=240),
        )
        seg = _segment_from_filters(filters)
        assert seg[11] is None
        assert seg[12] == 240

    def test_no_layover_restrictions(self):
        filters = _basic_filters()
        seg = _segment_from_filters(filters)
        assert seg[11] is None
        assert seg[12] is None


class TestDateSearchFiltersMirrors:
    """The new filter fields must also work on DateSearchFilters."""

    def test_date_search_excludes_at_position_5(self):
        filters = DateSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[_basic_segment()],
            from_date=_future_date(15),
            to_date=_future_date(60),
            airlines_exclude=[Airline.DL],
        )
        # Date-search outer envelope has filters at [1][13][i]
        seg = filters.format()[1][13][0]
        assert seg[5] == ["DL"]

    def test_date_search_alliance_include(self):
        filters = DateSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[_basic_segment()],
            from_date=_future_date(15),
            to_date=_future_date(60),
            alliances=[Alliance.ONEWORLD],
        )
        seg = filters.format()[1][13][0]
        assert seg[4] == ["ONEWORLD"]

    def test_date_search_min_layover_position_11(self):
        filters = DateSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[_basic_segment()],
            from_date=_future_date(15),
            to_date=_future_date(60),
            layover_restrictions=LayoverRestrictions(min_duration=45, max_duration=600),
        )
        seg = filters.format()[1][13][0]
        assert seg[11] == 45
        assert seg[12] == 600


class TestEncodingIsValidJSON:
    """The encoded payload must round-trip through JSON without crashing."""

    def test_full_filter_payload_serialisable(self):
        filters = _basic_filters(
            airlines=[Airline.DL, Airline.AA],
            airlines_exclude=[Airline.B6],
            alliances=[Alliance.ONEWORLD],
            alliances_exclude=[Alliance.STAR_ALLIANCE],
            layover_restrictions=LayoverRestrictions(
                airports=[Airport.ORD],
                min_duration=30,
                max_duration=600,
            ),
        )
        payload = filters.format()
        # Encode + decode should round-trip.
        json.loads(json.dumps(payload))
