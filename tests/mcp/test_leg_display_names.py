"""MCP flight results must show plain airport/airline names.

Names shared by several airports or airlines are stored with an internal
`` (CODE)`` suffix so every Enum value stays unique. That suffix must not leak
into tool responses: the code is already returned in its own field.
"""

import json
from datetime import datetime
from enum import Enum

from fli.mcp.server import _serialize_flight_leg as _serialize_leg
from fli.models import Airline, Airport, FlightLeg


def _leg(airline: Airline, origin: Airport, destination: Airport) -> FlightLeg:
    return FlightLeg(
        airline=airline,
        flight_number="6012",
        departure_airport=origin,
        arrival_airport=destination,
        departure_datetime=datetime(2026, 12, 15, 9, 25),
        arrival_datetime=datetime(2026, 12, 15, 11, 55),
        duration=150,
    )


def _as_json(payload: dict) -> dict:
    """Round-trip the way an MCP client receives it (Enums collapse to their value)."""

    def encode(value: object) -> object:
        return value.value if isinstance(value, Enum) else value.isoformat()

    return json.loads(json.dumps(payload, default=encode))


def test_disambiguated_names_are_shown_without_their_code_suffix():
    """OKA/NTL/W4 all carry an internal suffix; none of it reaches the response."""
    assert Airport.OKA.value.endswith("(OKA)")  # guards the premise of this test
    leg = _as_json(_serialize_leg(_leg(Airline.W4, Airport.OKA, Airport.NTL)))

    assert leg["departure_airport"] == "Naha Airport"
    assert leg["arrival_airport"] == "Newcastle Airport"
    assert leg["airline"] == "Wizz Air"
    assert leg["airline_code"] == "W4"


def test_ordinary_names_are_unchanged():
    """Names that were never ambiguous are returned exactly as before."""
    leg = _as_json(_serialize_leg(_leg(Airline.BA, Airport.JFK, Airport.LHR)))

    assert leg["departure_airport"] == Airport.JFK.value
    assert leg["arrival_airport"] == Airport.LHR.value
    assert leg["airline"] == Airline.BA.value


def test_duck_typed_legs_with_plain_strings_pass_through():
    """The serializer accepts leg-like objects whose names are already strings."""
    from types import SimpleNamespace

    leg = SimpleNamespace(
        airline="Example Air",
        flight_number="1",
        departure_airport="Somewhere (XYZ)",
        arrival_airport="Elsewhere",
        departure_datetime=datetime(2026, 12, 15, 9, 25),
        arrival_datetime=datetime(2026, 12, 15, 11, 55),
        duration=150,
    )
    out = _as_json(_serialize_leg(leg))

    assert out["departure_airport"] == "Somewhere (XYZ)"  # untouched: not an Enum member
    assert out["airline"] == "Example Air"
