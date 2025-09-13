"""MCP module for the fli package."""

from fli.mcp.server import (
    CheapFlightSearchRequest,
    FlightSearchRequest,
    mcp,
    run,
    run_http,
    search_cheap_flights,
    search_flights,
)

__all__ = [
    "CheapFlightSearchRequest",
    "FlightSearchRequest",
    "search_cheap_flights",
    "search_flights",
    "mcp",
    "run",
    "run_http",
]
