"""Tests for TimeRestrictions model."""

from fli.models import TimeRestrictions


def test_time_restrictions_no_swap_needed():
    """Test TimeRestrictions when times are in correct order."""
    tr = TimeRestrictions(
        earliest_departure=9,
        latest_departure=20,
        earliest_arrival=13,
        latest_arrival=21,
    )
    assert tr.earliest_departure == 9
    assert tr.latest_departure == 20
    assert tr.earliest_arrival == 13
    assert tr.latest_arrival == 21


def test_time_restrictions_departure_swap():
    """Test TimeRestrictions auto-swaps departure times when out of order."""
    tr = TimeRestrictions(
        earliest_departure=20,  # Later than latest_departure
        latest_departure=9,  # Earlier than earliest_departure
        earliest_arrival=13,
        latest_arrival=21,
    )
    assert tr.earliest_departure == 9  # Swapped
    assert tr.latest_departure == 20  # Swapped
    assert tr.earliest_arrival == 13  # Unchanged
    assert tr.latest_arrival == 21  # Unchanged


def test_time_restrictions_arrival_swap():
    """Test TimeRestrictions auto-swaps arrival times when out of order."""
    tr = TimeRestrictions(
        earliest_departure=9,
        latest_departure=20,
        earliest_arrival=21,  # Later than latest_arrival
        latest_arrival=13,  # Earlier than earliest_arrival
    )
    assert tr.earliest_departure == 9  # Unchanged
    assert tr.latest_departure == 20  # Unchanged
    assert tr.earliest_arrival == 13  # Swapped
    assert tr.latest_arrival == 21  # Swapped


def test_time_restrictions_both_swap():
    """Test TimeRestrictions auto-swaps both departure and arrival times when out of order."""
    tr = TimeRestrictions(
        earliest_departure=20,  # Later than latest_departure
        latest_departure=9,  # Earlier than earliest_departure
        earliest_arrival=21,  # Later than latest_arrival
        latest_arrival=13,  # Earlier than earliest_arrival
    )
    assert tr.earliest_departure == 9  # Swapped
    assert tr.latest_departure == 20  # Swapped
    assert tr.earliest_arrival == 13  # Swapped
    assert tr.latest_arrival == 21  # Swapped


def test_time_restrictions_partial_values():
    """Test TimeRestrictions with partial time restrictions."""
    # Only departure times
    tr1 = TimeRestrictions(
        earliest_departure=20,
        latest_departure=9,
    )
    assert tr1.earliest_departure == 9  # Swapped
    assert tr1.latest_departure == 20  # Swapped
    assert tr1.earliest_arrival is None
    assert tr1.latest_arrival is None

    # Only arrival times
    tr2 = TimeRestrictions(
        earliest_arrival=21,
        latest_arrival=13,
    )
    assert tr2.earliest_departure is None
    assert tr2.latest_departure is None
    assert tr2.earliest_arrival == 13  # Swapped
    assert tr2.latest_arrival == 21  # Swapped


def test_time_restrictions_single_values():
    """Test TimeRestrictions with single values (no swapping needed)."""
    tr1 = TimeRestrictions(earliest_departure=9)
    assert tr1.earliest_departure == 9
    assert tr1.latest_departure is None

    tr2 = TimeRestrictions(latest_departure=20)
    assert tr2.earliest_departure is None
    assert tr2.latest_departure == 20

    tr3 = TimeRestrictions(earliest_arrival=13)
    assert tr3.earliest_arrival == 13
    assert tr3.latest_arrival is None

    tr4 = TimeRestrictions(latest_arrival=21)
    assert tr4.earliest_arrival is None
    assert tr4.latest_arrival == 21
