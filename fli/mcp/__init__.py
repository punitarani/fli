"""MCP module for the fli package."""

from fli.mcp.server import (
    DateSearchParams,
    FlightSearchParams,
    mcp,
    run,
    run_http,
    search_dates,
    search_flights,
)

__all__ = [
    "DateSearchParams",
    "FlightSearchParams",
    "search_dates",
    "search_flights",
    "mcp",
    "run",
    "run_http",
]
