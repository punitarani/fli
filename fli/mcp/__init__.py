"""MCP module for the fli package."""

from fli.mcp.server import (
    CheapFlightSearchRequest,
    FlightSearchRequest,
    mcp,
    search_cheap_flights,
    search_flights,
)

__all__ = [
    "CheapFlightSearchRequest",
    "FlightSearchRequest",
    "search_cheap_flights",
    "search_flights",
    "mcp",
]
