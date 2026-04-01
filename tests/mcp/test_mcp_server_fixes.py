"""Tests for MCP server bug fixes.

Covers:
  1. list_tools FastMCP 2.x compatibility (get_tools async dict API)
  2. Round-trip price doubling (Google Flights returns combined RT price on outbound leg)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from fli.mcp.server import FliMCP, _serialize_flight_result

# ---------------------------------------------------------------------------
# Bug 1: list_tools — FastMCP 2.x compatibility
# ---------------------------------------------------------------------------


class TestListTools:
    """FliMCP.list_tools() must use the async get_tools() dict API."""

    @pytest.mark.asyncio
    async def test_list_tools_uses_get_tools(self):
        """list_tools() should call get_tools() (FastMCP 2.x) not list_tools()."""
        server = FliMCP("test")

        fake_tool = MagicMock()
        fake_tool.name = "search_flights"
        fake_tool.description = "Search flights"
        fake_tool.parameters = {}

        # get_tools() returns a dict in FastMCP 2.x
        server._tool_manager.get_tools = AsyncMock(return_value={"search_flights": fake_tool})

        tools = await server.list_tools()

        server._tool_manager.get_tools.assert_awaited_once()
        assert len(tools) == 1
        assert tools[0].name == "search_flights"

    @pytest.mark.asyncio
    async def test_list_tools_does_not_call_sync_list_tools(self):
        """list_tools() must not call the old synchronous list_tools() method."""
        server = FliMCP("test")

        server._tool_manager.get_tools = AsyncMock(return_value={})
        # If the old sync path is called it would raise AttributeError on FastMCP 2.x
        server._tool_manager.list_tools = MagicMock(
            side_effect=AttributeError("list_tools removed in FastMCP 2.x")
        )

        # Should not raise
        tools = await server.list_tools()
        server._tool_manager.list_tools.assert_not_called()
        assert tools == []


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
