"""MCP module for the fli package.

The MCP server depends on optional extras (``flights[mcp]``).  When those
packages are not installed the public names are simply unavailable and
importing this package will **not** raise an error.
"""

try:
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
except ModuleNotFoundError:
    __all__: list[str] = []
