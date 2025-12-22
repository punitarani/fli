"""Core utilities for flight search operations.

This module provides shared parsing and building utilities used by both
the CLI and MCP interfaces.
"""

from .builders import build_date_search_segments, build_flight_segments, build_time_restrictions
from .parsers import (
    parse_airlines,
    parse_cabin_class,
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
    "parse_max_stops",
    "parse_sort_by",
    "parse_time_range",
    "resolve_airport",
    "resolve_enum",
    # Builders
    "build_date_search_segments",
    "build_flight_segments",
    "build_time_restrictions",
]
