"""Tests that the MCP HTTP server boots and exposes the expected tools.

Covers:
  1. In-process client test — verifies tool listing without networking.
  2. HTTP transport test — starts the server on a free port and connects over HTTP.
"""

import threading
import time

import pytest
import uvicorn
from fastmcp import Client

from fli.mcp.server import mcp

EXPECTED_TOOLS = {"search_flights", "search_dates", "find_airports"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def http_mcp_url():
    """Boot the MCP server in a background thread and yield its base URL.

    Uses uvicorn port=0 so the OS assigns a free port at bind time, then reads
    the actual port back from the bound socket. This avoids the TOCTOU race of
    pre-allocating a port and hoping nothing else claims it before uvicorn binds.
    """
    app = mcp.http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            server.should_exit = True
            thread.join(timeout=5)
            pytest.fail("MCP HTTP server did not start in time")
        time.sleep(0.05)

    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/mcp/"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Test A: In-process (no network)
# ---------------------------------------------------------------------------


class TestMCPInProcess:
    """Verify MCP tool listing via the in-process FastMCP client."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_expected_names(self):
        """list_tools() must return the expected MCP tools."""
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
    async def test_http_list_tools(self, http_mcp_url):
        """Boot the HTTP server, connect, and verify tool names."""
        client = Client(http_mcp_url)
        async with client:
            tools = await client.list_tools()
        names = {t.name for t in tools}
        assert names == EXPECTED_TOOLS

    @pytest.mark.asyncio
    async def test_http_tools_have_description_and_schema(self, http_mcp_url):
        """Boot the HTTP server and verify each tool has description + schema."""
        client = Client(http_mcp_url)
        async with client:
            tools = await client.list_tools()
        for tool in tools:
            assert tool.description, f"{tool.name} is missing a description"
            assert tool.inputSchema, f"{tool.name} is missing inputSchema"
