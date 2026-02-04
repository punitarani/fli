"""Fli - A Python library for Google Flights API.

Provides programmatic access to Google Flights data through direct API interaction.

Usage::

    from fli import SearchFlights, SearchDates
    from fli.models import (
        Airport, Airline, FlightSearchFilters, FlightSegment,
        PassengerInfo, SeatType, MaxStops, SortBy,
    )

    search = SearchFlights()
    results = search.search(filters)

"""

from fli.search import DatePrice, SearchDates, SearchFlights

__all__ = [
    "SearchFlights",
    "SearchDates",
    "DatePrice",
]
