"""Tests for the multi-city CLI command."""

from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from fli.cli.main import app
from fli.models import Airline, Airport, FlightLeg, FlightResult, SeatType
from fli.models.google_flights.base import TripType


@pytest.fixture
def runner():
    """Return a CliRunner instance."""
    return CliRunner()


def _future_date(days_ahead: int = 30) -> str:
    """Return a future date string in YYYY-MM-DD format."""
    return (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def _make_multi_city_results():
    """Create mock multi-city results (3-tuple of FlightResults)."""
    now = datetime.now()
    return [
        (
            FlightResult(
                price=0.0,
                duration=600,
                stops=0,
                legs=[
                    FlightLeg(
                        airline=Airline.DL,
                        flight_number="DL100",
                        departure_airport=Airport.SEA,
                        arrival_airport=Airport.HKG,
                        departure_datetime=now,
                        arrival_datetime=now + timedelta(hours=10),
                        duration=600,
                    )
                ],
            ),
            FlightResult(
                price=0.0,
                duration=300,
                stops=0,
                legs=[
                    FlightLeg(
                        airline=Airline.CX,
                        flight_number="CX200",
                        departure_airport=Airport.HKG,
                        arrival_airport=Airport.PEK,
                        departure_datetime=now + timedelta(days=4),
                        arrival_datetime=now + timedelta(days=4, hours=5),
                        duration=300,
                    )
                ],
            ),
            FlightResult(
                price=2499.99,
                duration=660,
                stops=1,
                legs=[
                    FlightLeg(
                        airline=Airline.CA,
                        flight_number="CA300",
                        departure_airport=Airport.PEK,
                        arrival_airport=Airport.NRT,
                        departure_datetime=now + timedelta(days=7),
                        arrival_datetime=now + timedelta(days=7, hours=4),
                        duration=240,
                    ),
                    FlightLeg(
                        airline=Airline.DL,
                        flight_number="DL400",
                        departure_airport=Airport.NRT,
                        arrival_airport=Airport.SEA,
                        departure_datetime=now + timedelta(days=7, hours=6),
                        arrival_datetime=now + timedelta(days=7, hours=13),
                        duration=420,
                    ),
                ],
            ),
        )
    ]


class TestMultiCityCommand:
    """Tests for the multi command."""

    def test_basic_two_leg_search(self, runner, mock_search_flights, mock_console):
        """Test basic multi-city search with two legs."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            ["multi", "--leg", f"SEA,HKG,{date1}", "--leg", f"HKG,SEA,{date2}"],
        )
        assert result.exit_code == 0
        mock_search_flights.search.assert_called_once()

    def test_three_leg_search(self, runner, mock_search_flights, mock_console):
        """Test multi-city search with three legs."""
        mock_search_flights.search.return_value = _make_multi_city_results()

        date1 = _future_date(30)
        date2 = _future_date(34)
        date3 = _future_date(37)

        result = runner.invoke(
            app,
            [
                "multi",
                "--leg",
                f"SEA,HKG,{date1}",
                "--leg",
                f"HKG,PEK,{date2}",
                "--leg",
                f"PEK,SEA,{date3}",
            ],
        )
        assert result.exit_code == 0
        mock_search_flights.search.assert_called_once()
        args, _ = mock_search_flights.search.call_args
        assert args[0].trip_type == TripType.MULTI_CITY
        assert len(args[0].flight_segments) == 3

    def test_with_passengers(self, runner, mock_search_flights, mock_console):
        """Test multi-city search passes adult passenger count into filters."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            [
                "multi",
                "--leg",
                f"SEA,HKG,{date1}",
                "--leg",
                f"HKG,SEA,{date2}",
                "--passengers",
                "2",
            ],
        )
        assert result.exit_code == 0
        args, _ = mock_search_flights.search.call_args
        assert args[0].passenger_info.adults == 2

    def test_with_family_passenger_mix(self, runner, mock_search_flights, mock_console):
        """Test multi-city search passes the full passenger mix into filters."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            [
                "multi",
                "--leg",
                f"SEA,HKG,{date1}",
                "--leg",
                f"HKG,SEA,{date2}",
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

    def test_with_cabin_class(self, runner, mock_search_flights, mock_console):
        """Test multi-city search with cabin class filter."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            [
                "multi",
                "--leg",
                f"SEA,HKG,{date1}",
                "--leg",
                f"HKG,SEA,{date2}",
                "--class",
                "BUSINESS",
            ],
        )
        assert result.exit_code == 0
        mock_search_flights.build_flight_booking_url.assert_called()
        _, kwargs = mock_search_flights.build_flight_booking_url.call_args
        assert kwargs["seat_type"] == SeatType.BUSINESS

    def test_builds_booking_url_per_result(self, runner, mock_search_flights, mock_console):
        """Each result gets a booking deep-link, like the flights command already does."""
        mock_search_flights.search.return_value = _make_multi_city_results()
        date1 = _future_date(30)
        date2 = _future_date(34)
        date3 = _future_date(37)

        result = runner.invoke(
            app,
            [
                "multi",
                "--leg",
                f"SEA,HKG,{date1}",
                "--leg",
                f"HKG,PEK,{date2}",
                "--leg",
                f"PEK,SEA,{date3}",
            ],
        )
        assert result.exit_code == 0
        assert mock_search_flights.build_flight_booking_url.call_count == 1
        args, _ = mock_search_flights.build_flight_booking_url.call_args
        assert isinstance(args[0], tuple)
        assert len(args[0]) == 3

    def test_booking_url_reflects_passenger_mix(self, runner, mock_search_flights, mock_console):
        """The booking deep-link must be priced for the searched passenger mix, not a lone adult."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            [
                "multi",
                "--leg",
                f"SEA,HKG,{date1}",
                "--leg",
                f"HKG,SEA,{date2}",
                "--passengers",
                "2",
                "--children",
                "1",
            ],
        )
        assert result.exit_code == 0
        mock_search_flights.build_flight_booking_url.assert_called()
        _, kwargs = mock_search_flights.build_flight_booking_url.call_args
        assert kwargs["passenger_info"].adults == 2
        assert kwargs["passenger_info"].children == 1

    def test_with_stops_filter(self, runner, mock_search_flights, mock_console):
        """Test multi-city search with stops filter."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            [
                "multi",
                "--leg",
                f"SEA,HKG,{date1}",
                "--leg",
                f"HKG,SEA,{date2}",
                "--stops",
                "NON_STOP",
            ],
        )
        assert result.exit_code == 0

    def test_with_airlines_filter(self, runner, mock_search_flights, mock_console):
        """Test multi-city search with airline filter."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            [
                "multi",
                "--leg",
                f"SEA,HKG,{date1}",
                "--leg",
                f"HKG,SEA,{date2}",
                "-a",
                "DL",
                "-a",
                "CX",
            ],
        )
        assert result.exit_code == 0

    def test_with_time_filter(self, runner, mock_search_flights, mock_console):
        """Test multi-city search with departure time window."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            [
                "multi",
                "--leg",
                f"SEA,HKG,{date1}",
                "--leg",
                f"HKG,SEA,{date2}",
                "--time",
                "6-20",
            ],
        )
        assert result.exit_code == 0

    def test_short_flag(self, runner, mock_search_flights, mock_console):
        """Test multi-city search using -l short flag."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            ["multi", "-l", f"SEA,HKG,{date1}", "-l", f"HKG,SEA,{date2}"],
        )
        assert result.exit_code == 0


class TestMultiCityValidation:
    """Tests for multi-city command validation and error handling."""

    def test_single_leg_rejected(self, runner, mock_search_flights, mock_console):
        """Test that a single leg is rejected."""
        date1 = _future_date(30)

        result = runner.invoke(
            app,
            ["multi", "--leg", f"SEA,HKG,{date1}"],
        )
        assert result.exit_code == 1
        assert "at least 2 legs" in result.stdout

    def test_invalid_leg_format(self, runner, mock_search_flights, mock_console):
        """Test that invalid leg format is rejected."""
        result = runner.invoke(
            app,
            ["multi", "--leg", "SEA-HKG-2026-12-26", "--leg", "HKG-SEA-2027-01-02"],
        )
        assert result.exit_code != 0

    def test_invalid_airport_code(self, runner, mock_search_flights, mock_console):
        """Test that invalid airport codes are rejected."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            ["multi", "--leg", f"XXX,HKG,{date1}", "--leg", f"HKG,SEA,{date2}"],
        )
        assert result.exit_code == 1
        assert "Error" in result.stdout

    def test_invalid_date(self, runner, mock_search_flights, mock_console):
        """Test that invalid dates are rejected."""
        result = runner.invoke(
            app,
            ["multi", "--leg", "SEA,HKG,2026-13-45", "--leg", "HKG,SEA,2027-01-02"],
        )
        assert result.exit_code != 0

    def test_no_results(self, runner, mock_search_flights, mock_console):
        """Test multi-city search with no results."""
        mock_search_flights.search.return_value = []

        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            ["multi", "--leg", f"SEA,HKG,{date1}", "--leg", f"HKG,SEA,{date2}"],
        )
        assert result.exit_code == 1
        assert "No flights found" in result.stdout

    def test_invalid_passenger_mix_exits_nonzero_with_clean_message(
        self, runner, mock_search_flights, mock_console
    ):
        """A passenger mix Google Flights would reject fails cleanly, not with a pydantic dump."""
        date1 = _future_date(30)
        date2 = _future_date(37)

        result = runner.invoke(
            app,
            [
                "multi",
                "--leg",
                f"SEA,HKG,{date1}",
                "--leg",
                f"HKG,SEA,{date2}",
                "--passengers",
                "1",
                "--infants-on-lap",
                "3",
            ],
        )
        assert result.exit_code == 1
        assert "validation error for" not in result.stdout.lower()
        assert "infants_on_lap" in result.stdout
        mock_search_flights.search.assert_not_called()
