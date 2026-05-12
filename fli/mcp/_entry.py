"""Thin entry-point wrappers for the MCP server commands.

These wrappers exist so that the ``fli-mcp`` and ``fli-mcp-http`` console
scripts can be registered unconditionally in ``pyproject.toml`` while still
giving a helpful error message when the optional ``[mcp]`` dependencies are
not installed.
"""

import sys


def run() -> None:
    """Run the MCP server on STDIO."""
    try:
        from fli.mcp.server import run as _run
    except ModuleNotFoundError:
        print(
            "MCP dependencies are not installed.\nInstall them with:  pip install 'flights[mcp]'",
            file=sys.stderr,
        )
        sys.exit(1)
    _run()


def run_http() -> None:
    """Run the MCP server over HTTP (streamable)."""
    try:
        from fli.mcp.server import run_http as _run_http
    except ModuleNotFoundError:
        print(
            "MCP dependencies are not installed.\nInstall them with:  pip install 'flights[mcp]'",
            file=sys.stderr,
        )
        sys.exit(1)
    _run_http()
