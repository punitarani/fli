"""Tests that the MCP HTTP server boots and exposes the expected tools.

Covers:
  1. In-process client test — verifies tool listing without networking.
  2. HTTP transport test — starts the server on a free port and connects over HTTP.
"""

import socket
import threading
import time

import pytest
import uvicorn
from fastmcp import Client

from fli.mcp.server import mcp

EXPECTED_TOOLS = {"search_flights", "search_dates"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Return an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Test A: In-process (no network)
# ---------------------------------------------------------------------------


class TestMCPInProcess:
    """Verify MCP tool listing via the in-process FastMCP client."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_expected_names(self):
        """list_tools() must return search_flights and search_dates."""
        client = Client(mcp)
        async with client:
            tools = await client.list_tools()
        names = {t.name for t in tools}
        assert names == EXPECTED_TOOLS

    @pytest.mark.asyncio
    async def test_tools_have_description_and_schema(self):
        """Each tool must have a non-empty description and an inputSchema."""
        client = Client(mcp)
        async with client:
            tools = await client.list_tools()
        for tool in tools:
            assert tool.description, f"{tool.name} is missing a description"
            assert tool.inputSchema, f"{tool.name} is missing inputSchema"


# ---------------------------------------------------------------------------
# Test B: HTTP transport (full integration)
# ---------------------------------------------------------------------------


class TestMCPHTTP:
    """Start the MCP server over HTTP and verify tools via a real connection."""

    @pytest.mark.asyncio
    async def test_http_list_tools(self):
        """Boot the HTTP server, connect, and verify tool names."""
        port = _free_port()

        app = mcp.http_app()
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)

        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        # Wait for the server to accept connections.
        for _ in range(40):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                    break
            except OSError:
                time.sleep(0.25)
        else:
            pytest.fail("MCP HTTP server did not start in time")

        try:
            client = Client(f"http://127.0.0.1:{port}/mcp/")
            async with client:
                tools = await client.list_tools()
            names = {t.name for t in tools}
            assert names == EXPECTED_TOOLS
        finally:
            server.should_exit = True
            thread.join(timeout=5)

    @pytest.mark.asyncio
    async def test_http_tools_have_description_and_schema(self):
        """Boot the HTTP server and verify each tool has description + schema."""
        port = _free_port()

        app = mcp.http_app()
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)

        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        for _ in range(40):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                    break
            except OSError:
                time.sleep(0.25)
        else:
            pytest.fail("MCP HTTP server did not start in time")

        try:
            client = Client(f"http://127.0.0.1:{port}/mcp/")
            async with client:
                tools = await client.list_tools()
            for tool in tools:
                assert tool.description, f"{tool.name} is missing a description"
                assert tool.inputSchema, f"{tool.name} is missing inputSchema"
        finally:
            server.should_exit = True
            thread.join(timeout=5)
