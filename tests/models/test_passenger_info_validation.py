"""Tests for PassengerInfo validation.

Google Flights caps a single booking at 9 total passengers and requires
every lap infant to be paired with an adult. Without validation,
``PassengerInfo(adults=1, infants_on_lap=3)`` or 20 adults built fine and
silently produced a wrong quote.
"""

import pytest

from fli.models import PassengerInfo


def test_single_adult_is_valid():
    """Test the default single-adult mix is accepted."""
    info = PassengerInfo(adults=1)
    assert info.adults == 1
    assert info.children == 0
    assert info.infants_in_seat == 0
    assert info.infants_on_lap == 0


def test_total_of_nine_is_accepted():
    """Test the maximum allowed total of 9 passengers is accepted."""
    info = PassengerInfo(adults=4, children=2, infants_in_seat=2, infants_on_lap=1)
    assert info.adults + info.children + info.infants_in_seat + info.infants_on_lap == 9


def test_total_of_ten_is_rejected():
    """Test a total of 10 passengers is rejected."""
    with pytest.raises(ValueError, match="Total passengers must be between 1 and 9"):
        PassengerInfo(adults=4, children=2, infants_in_seat=2, infants_on_lap=2)


def test_total_of_zero_is_rejected():
    """Test zero total passengers is rejected."""
    with pytest.raises(ValueError, match="Total passengers must be between 1 and 9"):
        PassengerInfo(adults=0, children=0, infants_in_seat=0, infants_on_lap=0)


def test_lap_infants_equal_to_adults_is_accepted():
    """Test infants_on_lap == adults is accepted (one lap infant per adult)."""
    info = PassengerInfo(adults=2, infants_on_lap=2)
    assert info.infants_on_lap == info.adults


def test_lap_infants_exceeding_adults_is_rejected():
    """Test infants_on_lap > adults is rejected (each lap infant needs an adult)."""
    with pytest.raises(ValueError, match="infants_on_lap"):
        PassengerInfo(adults=1, infants_on_lap=3)


def test_error_message_names_offending_values():
    """Test the total-passengers error names the actual counts, not just the rule."""
    with pytest.raises(ValueError, match=r"got 10"):
        PassengerInfo(adults=9, children=1)


def test_lap_infants_error_names_offending_values():
    """Test the lap-infants error names the actual adults/infants_on_lap values."""
    with pytest.raises(ValueError, match=r"infants_on_lap \(3\).*adults \(1\)"):
        PassengerInfo(adults=1, infants_on_lap=3)
