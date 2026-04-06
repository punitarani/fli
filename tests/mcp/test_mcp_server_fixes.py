"""Tests for MCP server bug fixes.

Covers:
  1. list_tools FastMCP 3.x registration and annotations
  2. Round-trip price doubling (Google Flights returns combined RT price on outbound leg)
"""

from unittest.mock import MagicMock

import pytest
from fastmcp import FastMCP

from fli.mcp.server import _serialize_flight_result, mcp

# ---------------------------------------------------------------------------
# Bug 1: list_tools — FastMCP 3.x compatibility
# ---------------------------------------------------------------------------


class TestListTools:
    """FliMCP.list_tools() should expose native FastMCP 3 tool metadata."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_registered_tools_with_annotations(self):
        """Registered tools should be listed with their schemas and annotations."""
        server = FastMCP("test")

        @server.tool(
            description="Search flights",
            annotations={"title": "Search Flights", "readOnlyHint": True, "idempotentHint": True},
        )
        def search_flights(origin: str, destination: str) -> dict[str, str]:
            return {"origin": origin, "destination": destination}

        tools = await server.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "search_flights"
        assert tools[0].description == "Search flights"
        assert tools[0].parameters["type"] == "object"
        assert tools[0].parameters["properties"]["origin"]["type"] == "string"
        assert tools[0].parameters["properties"]["destination"]["type"] == "string"
        assert tools[0].annotations.title == "Search Flights"
        assert tools[0].annotations.readOnlyHint is True
        assert tools[0].annotations.idempotentHint is True

    def test_tool_decorator_preserves_function_usage(self):
        """The FastMCP 3 decorator should still leave a normal callable behind."""
        server = FastMCP("test")

        @server.tool()
        def search_flights(origin: str, destination: str) -> dict[str, str]:
            return {"route": f"{origin}-{destination}"}

        assert search_flights("JFK", "LHR") == {"route": "JFK-LHR"}


class TestPrompts:
    """Module prompts should use FastMCP 3's native prompt registration."""

    @pytest.mark.asyncio
    async def test_builtin_prompts_are_registered_and_render(self):
        """The module-level prompts should be listable and render expected guidance."""
        prompts = await mcp.list_prompts()
        prompt_names = {prompt.name for prompt in prompts}

        assert "search-direct-flight" in prompt_names
        assert "find-budget-window" in prompt_names

        result = await mcp.render_prompt(
            "search-direct-flight",
            {"origin": "jfk", "destination": "lhr", "prefer_non_stop": "true"},
        )
        assert result.messages[0].content.text.startswith(
            "Use the `search_flights` tool to look for flights from JFK to LHR"
        )
        assert "NON_STOP" in result.messages[0].content.text


# ---------------------------------------------------------------------------
# Bug 2: Round-trip price doubling
# ---------------------------------------------------------------------------


def _make_leg(airport_from="TLV", airport_to="ATH"):
    leg = MagicMock()
    leg.departure_airport = airport_from
    leg.arrival_airport = airport_to
    leg.departure_datetime = None
    leg.arrival_datetime = None
    leg.duration = 145
    leg.airline = "Wizz Air"
    leg.flight_number = "W6100"
    return leg


def _make_flight(price, legs=None):
    flight = MagicMock()
    flight.price = price
    flight.currency = "USD"
    flight.legs = legs or [_make_leg()]
    return flight


class TestSerializeFlightResult:
    """_serialize_flight_result must not double round-trip prices."""

    def test_one_way_price_unchanged(self):
        """One-way flight price should pass through unchanged."""
        flight = _make_flight(price=250.0)
        result = _serialize_flight_result(flight, is_round_trip=False)
        assert result["price"] == 250.0
        assert result["currency"] == "USD"

    def test_round_trip_uses_outbound_price_only(self):
        """Round-trip price must equal outbound.price (Google already includes full RT price)."""
        outbound = _make_flight(price=454.0, legs=[_make_leg("TLV", "ATH")])
        return_flight = _make_flight(price=454.0, legs=[_make_leg("ATH", "TLV")])

        result = _serialize_flight_result((outbound, return_flight), is_round_trip=True)

        # Must NOT be 454 + 454 = 908
        assert result["price"] == 454.0, (
            f"Expected 454.0 (outbound price only), got {result['price']}. "
            "Google Flights already includes the full RT price on the outbound leg."
        )

    def test_round_trip_price_not_doubled(self):
        """Explicit check that the price is not the sum of both legs."""
        outbound = _make_flight(price=300.0)
        return_flight = _make_flight(price=300.0)

        result = _serialize_flight_result((outbound, return_flight), is_round_trip=True)

        assert result["price"] != 600.0, "Price must not be doubled"
        assert result["price"] == 300.0

    def test_round_trip_includes_legs_from_both_directions(self):
        """Round-trip result must include legs from both outbound and return flights."""
        outbound_leg = _make_leg("TLV", "ATH")
        return_leg = _make_leg("ATH", "TLV")
        outbound = _make_flight(price=454.0, legs=[outbound_leg])
        return_flight = _make_flight(price=454.0, legs=[return_leg])

        result = _serialize_flight_result((outbound, return_flight), is_round_trip=True)

        assert len(result["legs"]) == 2

    def test_round_trip_non_tuple_falls_back_to_single_flight(self):
        """If flight is not a tuple, treat it as a one-way even if is_round_trip=True."""
        flight = _make_flight(price=500.0)
        result = _serialize_flight_result(flight, is_round_trip=True)
        assert result["price"] == 500.0

    def test_multi_city_three_legs(self):
        """Multi-city (3-leg) tuple should serialize without crashing."""
        leg1 = _make_flight(price=0.0, legs=[_make_leg("JFK", "LAX")])
        leg2 = _make_flight(price=0.0, legs=[_make_leg("LAX", "ORD")])
        leg3 = _make_flight(price=750.0, legs=[_make_leg("ORD", "JFK")])

        result = _serialize_flight_result((leg1, leg2, leg3), is_round_trip=False)

        assert result["price"] == 750.0
        assert len(result["legs"]) == 3

    def test_multi_city_not_treated_as_round_trip(self):
        """A 3-leg tuple must not be treated as round-trip even if flag is True."""
        leg1 = _make_flight(price=0.0, legs=[_make_leg("JFK", "LAX")])
        leg2 = _make_flight(price=0.0, legs=[_make_leg("LAX", "ORD")])
        leg3 = _make_flight(price=900.0, legs=[_make_leg("ORD", "JFK")])

        result = _serialize_flight_result((leg1, leg2, leg3), is_round_trip=True)

        assert result["price"] == 900.0
        assert len(result["legs"]) == 3

    def test_two_tuple_without_round_trip_uses_outbound_price(self):
        """A 2-element tuple with is_round_trip=False should use outbound price."""
        outbound = _make_flight(price=350.0, legs=[_make_leg("JFK", "LAX")])
        return_flight = _make_flight(price=350.0, legs=[_make_leg("LAX", "JFK")])

        result = _serialize_flight_result((outbound, return_flight), is_round_trip=False)

        assert result["price"] == 350.0
        assert len(result["legs"]) == 2

    def test_uses_flight_currency_when_available(self):
        """Serialization should emit the per-result returned currency."""
        flight = _make_flight(price=275.0)
        flight.currency = "EUR"

        result = _serialize_flight_result(flight, is_round_trip=False)

        assert result["currency"] == "EUR"
