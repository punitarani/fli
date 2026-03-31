"""Core utilities for flight search operations.

This module provides shared parsing and building utilities used by both
the CLI and MCP interfaces.
"""

from .builders import (
    build_date_search_segments,
    build_flight_segments,
    build_multi_city_segments,
    build_time_restrictions,
)
from .currency import extract_currency_from_price_token, format_price, format_price_axis_label
from .parsers import (
    parse_airlines,
    parse_cabin_class,
    parse_emissions,
    parse_max_stops,
    parse_sort_by,
    parse_time_range,
    resolve_airport,
    resolve_enum,
)

__all__ = [
    # Parsers
    "parse_airlines",
    "parse_cabin_class",
    "parse_emissions",
    "parse_max_stops",
    "parse_sort_by",
    "parse_time_range",
    "resolve_airport",
    "resolve_enum",
    # Builders
    "build_date_search_segments",
    "build_flight_segments",
    "build_multi_city_segments",
    "build_time_restrictions",
    # Currency
    "extract_currency_from_price_token",
    "format_price",
    "format_price_axis_label",
]
