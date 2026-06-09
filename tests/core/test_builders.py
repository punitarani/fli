import pytest

from fli.core.builders import build_date_search_segments, build_flight_segments, normalize_date
from fli.models import Airport, TimeRestrictions, TripType


class TestNormalizeDate:
    """Tests for normalize_date."""

    def test_already_padded(self):
        assert normalize_date("2027-04-02") == "2027-04-02"

    def test_single_digit_month_and_day(self):
        assert normalize_date("2027-4-2") == "2027-04-02"

    def test_single_digit_day(self):
        assert normalize_date("2027-12-5") == "2027-12-05"

    def test_single_digit_month(self):
        assert normalize_date("2027-1-15") == "2027-01-15"

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            normalize_date("not-a-date")

    def test_invalid_month_raises(self):
        with pytest.raises(ValueError):
            normalize_date("2027-13-01")


class TestBuildFlightSegments:
    """Tests for date normalization in build_flight_segments."""

    def test_normalizes_departure_date(self):
        segments, _ = build_flight_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            departure_date="2027-1-15",
        )
        assert segments[0].travel_date == "2027-01-15"

    def test_normalizes_return_date(self):
        segments, trip_type = build_flight_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            departure_date="2027-1-15",
            return_date="2027-1-22",
        )
        assert trip_type == TripType.ROUND_TRIP
        assert segments[0].travel_date == "2027-01-15"
        assert segments[1].travel_date == "2027-01-22"


class TestBuildDateSearchSegments:
    """Tests for date normalization in build_date_search_segments."""

    def test_normalizes_start_date(self):
        segments, _ = build_date_search_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            start_date="2027-1-15",
        )
        assert segments[0].travel_date == "2027-01-15"

    def test_normalizes_start_date_round_trip(self):
        segments, trip_type = build_date_search_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            start_date="2027-1-15",
            is_round_trip=True,
            trip_duration=7,
        )
        assert trip_type == TripType.ROUND_TRIP
        assert segments[0].travel_date == "2027-01-15"
        assert segments[1].travel_date == "2027-01-22"


class TestBuildFlightSegmentsMultiAirport:
    """Tests for multi-airport support in build_flight_segments."""

    def test_single_airport_wraps_to_list(self):
        segments, _ = build_flight_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            departure_date="2027-03-15",
        )
        assert segments[0].departure_airport == [[Airport.JFK, 0]]
        assert segments[0].arrival_airport == [[Airport.LAX, 0]]

    def test_list_of_origins(self):
        segments, _ = build_flight_segments(
            origin=[Airport.JFK, Airport.LGA],
            destination=Airport.LHR,
            departure_date="2027-03-15",
        )
        assert segments[0].departure_airport == [[Airport.JFK, 0], [Airport.LGA, 0]]
        assert segments[0].arrival_airport == [[Airport.LHR, 0]]

    def test_list_of_destinations(self):
        segments, _ = build_flight_segments(
            origin=Airport.JFK,
            destination=[Airport.LHR, Airport.CDG],
            departure_date="2027-03-15",
        )
        assert segments[0].departure_airport == [[Airport.JFK, 0]]
        assert segments[0].arrival_airport == [[Airport.LHR, 0], [Airport.CDG, 0]]

    def test_lists_on_both_sides(self):
        segments, _ = build_flight_segments(
            origin=[Airport.JFK, Airport.LGA, Airport.EWR],
            destination=[Airport.LHR, Airport.CDG],
            departure_date="2027-03-15",
        )
        assert segments[0].departure_airport == [
            [Airport.JFK, 0],
            [Airport.LGA, 0],
            [Airport.EWR, 0],
        ]
        assert segments[0].arrival_airport == [[Airport.LHR, 0], [Airport.CDG, 0]]

    def test_round_trip_mirrors_multi_airport(self):
        segments, trip_type = build_flight_segments(
            origin=[Airport.JFK, Airport.LGA],
            destination=[Airport.LHR, Airport.CDG],
            departure_date="2027-03-15",
            return_date="2027-03-22",
        )
        assert trip_type == TripType.ROUND_TRIP
        assert segments[0].departure_airport == [[Airport.JFK, 0], [Airport.LGA, 0]]
        assert segments[0].arrival_airport == [[Airport.LHR, 0], [Airport.CDG, 0]]
        assert segments[1].departure_airport == [[Airport.LHR, 0], [Airport.CDG, 0]]
        assert segments[1].arrival_airport == [[Airport.JFK, 0], [Airport.LGA, 0]]


class TestBuildDateSearchSegmentsMultiAirport:
    """Tests for multi-airport support in build_date_search_segments."""

    def test_single_airport_wraps_to_list(self):
        segments, _ = build_date_search_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            start_date="2027-03-15",
        )
        assert segments[0].departure_airport == [[Airport.JFK, 0]]
        assert segments[0].arrival_airport == [[Airport.LAX, 0]]

    def test_list_inputs_preserved(self):
        segments, _ = build_date_search_segments(
            origin=[Airport.JFK, Airport.LGA],
            destination=[Airport.LHR, Airport.CDG],
            start_date="2027-03-15",
        )
        assert segments[0].departure_airport == [[Airport.JFK, 0], [Airport.LGA, 0]]
        assert segments[0].arrival_airport == [[Airport.LHR, 0], [Airport.CDG, 0]]

    def test_round_trip_mirrors_multi_airport(self):
        segments, trip_type = build_date_search_segments(
            origin=[Airport.JFK, Airport.LGA],
            destination=[Airport.LHR, Airport.CDG],
            start_date="2027-03-15",
            is_round_trip=True,
            trip_duration=7,
        )
        assert trip_type == TripType.ROUND_TRIP
        assert segments[0].departure_airport == [[Airport.JFK, 0], [Airport.LGA, 0]]
        assert segments[0].arrival_airport == [[Airport.LHR, 0], [Airport.CDG, 0]]
        assert segments[1].departure_airport == [[Airport.LHR, 0], [Airport.CDG, 0]]
        assert segments[1].arrival_airport == [[Airport.JFK, 0], [Airport.LGA, 0]]


class TestReturnTimeRestrictions:
    """Tests for return_time_restrictions parameter in both builders."""

    OUTBOUND = TimeRestrictions(earliest_departure=6, latest_departure=16)
    RETURN = TimeRestrictions(earliest_departure=8, latest_departure=22)

    def test_build_flight_segments_default_inherits_outbound(self):
        """Without return_time_restrictions, return segment mirrors outbound restrictions."""
        segments, _ = build_flight_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            departure_date="2027-03-15",
            return_date="2027-03-22",
            time_restrictions=self.OUTBOUND,
        )
        assert segments[0].time_restrictions == self.OUTBOUND
        assert segments[1].time_restrictions == self.OUTBOUND

    def test_build_flight_segments_none_clears_return(self):
        """return_time_restrictions=None means no filter on the return leg."""
        segments, _ = build_flight_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            departure_date="2027-03-15",
            return_date="2027-03-22",
            time_restrictions=self.OUTBOUND,
            return_time_restrictions=None,
        )
        assert segments[0].time_restrictions == self.OUTBOUND
        assert segments[1].time_restrictions is None

    def test_build_flight_segments_separate_return_window(self):
        """return_time_restrictions overrides the outbound restrictions for the return leg."""
        segments, _ = build_flight_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            departure_date="2027-03-15",
            return_date="2027-03-22",
            time_restrictions=self.OUTBOUND,
            return_time_restrictions=self.RETURN,
        )
        assert segments[0].time_restrictions == self.OUTBOUND
        assert segments[1].time_restrictions == self.RETURN

    def test_build_date_search_segments_default_inherits_outbound(self):
        """Without return_time_restrictions, return segment mirrors outbound restrictions."""
        segments, _ = build_date_search_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            start_date="2027-03-15",
            is_round_trip=True,
            trip_duration=7,
            time_restrictions=self.OUTBOUND,
        )
        assert segments[0].time_restrictions == self.OUTBOUND
        assert segments[1].time_restrictions == self.OUTBOUND

    def test_build_date_search_segments_none_clears_return(self):
        """return_time_restrictions=None means no filter on the return leg."""
        segments, _ = build_date_search_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            start_date="2027-03-15",
            is_round_trip=True,
            trip_duration=7,
            time_restrictions=self.OUTBOUND,
            return_time_restrictions=None,
        )
        assert segments[0].time_restrictions == self.OUTBOUND
        assert segments[1].time_restrictions is None

    def test_build_date_search_segments_separate_return_window(self):
        """return_time_restrictions overrides the outbound restrictions for the return leg."""
        segments, _ = build_date_search_segments(
            origin=Airport.JFK,
            destination=Airport.LAX,
            start_date="2027-03-15",
            is_round_trip=True,
            trip_duration=7,
            time_restrictions=self.OUTBOUND,
            return_time_restrictions=self.RETURN,
        )
        assert segments[0].time_restrictions == self.OUTBOUND
        assert segments[1].time_restrictions == self.RETURN
