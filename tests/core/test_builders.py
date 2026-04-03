import pytest

from fli.core.builders import build_date_search_segments, build_flight_segments, normalize_date
from fli.models import Airport, TripType


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
