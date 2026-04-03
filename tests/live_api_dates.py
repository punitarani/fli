"""Shared future-safe dates for tests that hit the live Google Flights API."""

from datetime import date, timedelta

PRIMARY_TRAVEL_OFFSET_DAYS = 45
SECONDARY_TRAVEL_OFFSET_DAYS = 75
SHORT_RETURN_OFFSET_DAYS = 7
LONG_RETURN_OFFSET_DAYS = 14
WINDOW_PADDING_DAYS = 14


def live_api_date(days_ahead: int) -> str:
    """Return a date string safely in the future for live API calls."""
    return (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def live_api_window(
    travel_offset_days: int, *, padding_days: int = WINDOW_PADDING_DAYS
) -> tuple[str, str]:
    """Return a strictly-future date window around a travel date."""
    return (
        live_api_date(travel_offset_days - padding_days),
        live_api_date(travel_offset_days + padding_days),
    )
