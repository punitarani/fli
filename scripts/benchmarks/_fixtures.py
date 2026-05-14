"""Synthetic fixture builders for the benchmark suite.

Captured fixtures only give us one shape per file. To cover scaling
behaviour (many rows, deep layovers, etc.) we synthesise additional
fixtures from primitives that mirror the live response layout. The
synthesisers live here so both the bench and the comparison scripts
share one source of truth.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta


def _leg(
    *,
    dep="JFK",
    arr="LAX",
    dep_date=(2026, 7, 15),
    arr_date=(2026, 7, 15),
    dep_time=(8, 0),
    arr_time=(11, 30),
    duration=210,
    airline="DL",
    flight_no="123",
    aircraft="Boeing 737",
):
    """Mirror the 33-element leg array layout from Google's response."""
    leg = [None] * 33
    leg[3] = dep
    leg[4] = f"{dep} Airport"
    leg[5] = f"{arr} Airport"
    leg[6] = arr
    leg[8] = list(dep_time)
    leg[10] = list(arr_time)
    leg[11] = duration
    leg[12] = [None, True, None, None, None, True, None, None, None, True, None, 2]
    leg[14] = "31 in"
    leg[17] = aircraft
    leg[19] = False
    leg[20] = list(dep_date)
    leg[21] = list(arr_date)
    leg[22] = [airline, flight_no, None, "Carrier Name"]
    leg[25] = 1
    leg[30] = "31 inches"
    leg[31] = 224000
    leg[32] = 2
    return leg


def _row(legs: list, *, price: float = 200.0, currency_token: str = "CAUaAlVTKAEgASoCVVMyAlVT"):
    """Mirror the 11-element row + 25-element detail layouts."""
    detail = [None] * 25
    detail[0] = legs[0][22][0]
    detail[1] = [legs[0][22][3]]
    detail[2] = legs
    detail[3] = legs[0][3]
    detail[4] = legs[0][20]
    detail[5] = legs[0][8]
    detail[6] = legs[-1][6]
    detail[7] = legs[-1][21]
    detail[8] = legs[-1][10]
    detail[9] = sum(leg[11] for leg in legs)
    detail[12] = False
    emissions = [None] * 18
    emissions[3] = -10
    emissions[7] = 220000
    emissions[8] = 245000
    emissions[10] = 280000
    emissions[11] = 1
    detail[22] = emissions
    row = [None] * 11
    row[0] = detail
    row[1] = [[None, price], currency_token]
    row[8] = f"BOOKING_TOKEN_{int(price)}"
    row[10] = False
    return row


def _nonstop_row(i: int) -> list:
    return _row([_leg(flight_no=str(100 + i))], price=200.0 + i)


def _multi_leg_row(i: int) -> list:
    leg1 = _leg(
        dep="JFK",
        arr="CDG",
        dep_time=(19, 0),
        arr_time=(9, 0),
        dep_date=(2026, 7, 15),
        arr_date=(2026, 7, 16),
        duration=480,
        airline="AF",
        flight_no=f"{300 + i}",
    )
    leg2 = _leg(
        dep="CDG",
        arr="ATH",
        dep_time=(13, 0),
        arr_time=(17, 0),
        dep_date=(2026, 7, 16),
        arr_date=(2026, 7, 16),
        duration=240,
        airline="AF",
        flight_no=f"{800 + i}",
    )
    return _row([leg1, leg2], price=650.0 + i)


def synthetic_flight_response(*, rows: int, multi_leg: bool = False) -> str:
    """Build a fixture body with ``rows`` flight rows in the live wire format."""
    builder = _multi_leg_row if multi_leg else _nonstop_row
    flight_rows = [builder(i) for i in range(rows)]
    # Match the live layout: inner[2][0] is the flight-row list, inner[3][0] also.
    inner = [None, None, [flight_rows], [[]]]
    return ")]}'\n" + json.dumps([["wrb.fr", None, json.dumps(inner)]])


def synthetic_multi_chunk_flight_response(*, rows_per_chunk: int, chunks: int) -> str:
    r"""Build a multi-chunk wire body to exercise the streaming reader.

    Google's framing: ``<len>\n<json_bytes>\n``. The length header counts
    the chunk's bytes — JSON + trailing newline — plus 1 (the convention
    the reader compensates for with ``length - 1``).
    """
    parts = [")]}'\n\n"]
    for c in range(chunks):
        rows = [_nonstop_row(c * rows_per_chunk + i) for i in range(rows_per_chunk)]
        inner = [None, None, [rows], [[]]]
        payload = json.dumps([["wrb.fr", None, json.dumps(inner)]])
        encoded = payload.encode("utf-8")
        chunk_bytes = len(encoded) + 1  # +1 for trailing newline counted in the chunk
        parts.append(f"{chunk_bytes + 1}\n")
        parts.append(payload)
        parts.append("\n")
    return "".join(parts)


def synthetic_date_response(days: int = 61) -> str:
    """Build a ``GetCalendarGraph`` body with ``days`` date entries."""
    base = datetime(2026, 7, 1)
    entries = [
        [
            (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            None,
            [[None, 150 + i], "CAUaAlVTKAEgASoCVVMyAlVT"],
        ]
        for i in range(days)
    ]
    inner = json.dumps([None, None, entries])
    return ")]}'\n" + json.dumps([["wrb.fr", None, inner]])


def synthetic_booking_response(*, vendor_count: int) -> str:
    """Build a ``GetBookingResults`` body with ``vendor_count`` options."""
    booking_rows = []
    for i in range(vendor_count):
        row = [None] * 25
        row[0] = i
        row[1] = [[f"V{i:02d}", f"Vendor {i}", None, i % 2 == 0]]
        row[3] = [["AA", str(100 + i)]]
        row[5] = [f"https://vendor{i}.example/book", None, ["https://google.com/travel/clk?v=1"]]
        row[7] = [[None, 250.0 + i], "CAUaAlVTKAEgASoCVVMyAlVT"]
        row[21] = [None, None, None, f"Fare class {i}"]
        booking_rows.append(row)

    inner = [None, [booking_rows]]
    return ")]}'\n" + json.dumps([["wrb.fr", None, json.dumps(inner)]])
