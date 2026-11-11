"""Dump the golden ``tfs`` values pinned by ``tests/search/tfs.test.ts``.

The TypeScript encoder must produce byte-identical ``tfs`` tokens to the
Python one — that is the strongest correctness lever the port has, since
Google accepts a malformed token by quietly answering a different query.
This script is the single source of those goldens.

Run it from the **repository root** (it imports the Python package, not
the JS one)::

    uv run --python 3.13 python fli-js/scripts/dump_tfs_goldens.py

and paste the JSON it prints into ``TFS_GOLDENS`` in
``fli-js/tests/search/tfs.test.ts``.

Travel dates are deliberately far out: ``FlightSegment`` rejects a past
date, and the JS suite has no clock-pinning fixture, so a golden built on
a near date would start failing the day it passed. The ``tfs`` bytes
depend only on the dates in the filters, never on "today".
"""

from __future__ import annotations

import json
from datetime import datetime

from fli.models import (
    Airline,
    Airport,
    Alliance,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    LayoverRestrictions,
    MaxStops,
    PassengerInfo,
    SeatType,
    TripType,
)
from fli.search._tfs import build_tfs

OUT = "2030-09-15"
RET = "2030-09-19"
MULTI = "2030-10-15"


def seg(origins, dests, date):
    return FlightSegment(
        departure_airport=[[Airport[o], 0] for o in origins],
        arrival_airport=[[Airport[d], 0] for d in dests],
        travel_date=date,
    )


def filters(segments, **kw):
    return FlightSearchFilters(
        trip_type=kw.pop("trip_type", TripType.ONE_WAY),
        passenger_info=kw.pop("passenger_info", PassengerInfo(adults=1)),
        flight_segments=segments,
        stops=kw.pop("stops", MaxStops.ANY),
        seat_type=kw.pop("seat_type", SeatType.ECONOMY),
        **kw,
    )


def selected_flight():
    return FlightResult(
        legs=[
            FlightLeg(
                airline=Airline.BA,
                flight_number="178",
                departure_airport=Airport.JFK,
                arrival_airport=Airport.LHR,
                departure_datetime=datetime(2030, 9, 15, 20, 30),
                arrival_datetime=datetime(2030, 9, 16, 8, 30),
                duration=420,
            )
        ],
        price=295.0,
        currency="USD",
        duration=420,
        stops=0,
    )


def two_leg_selected_flight():
    """Connecting outbound, to pin the repeated leg encoding."""
    return FlightResult(
        legs=[
            FlightLeg(
                airline=Airline.AA,
                flight_number="100",
                departure_airport=Airport.JFK,
                arrival_airport=Airport.ORD,
                departure_datetime=datetime(2030, 9, 15, 7, 0),
                arrival_datetime=datetime(2030, 9, 15, 9, 0),
                duration=150,
            ),
            FlightLeg(
                airline=Airline.AA,
                flight_number="200",
                departure_airport=Airport.ORD,
                arrival_airport=Airport.LHR,
                departure_datetime=datetime(2030, 9, 15, 17, 0),
                arrival_datetime=datetime(2030, 9, 16, 7, 0),
                duration=480,
            ),
        ],
        price=420.0,
        currency="USD",
        duration=900,
        stops=1,
    )


cases: dict[str, str] = {}


def add(name, spec, **kw):
    cases[name] = build_tfs(spec, **kw)


# --- trip shapes ---------------------------------------------------------
add("one_way_jfk_lax", filters([seg(["JFK"], ["LAX"], OUT)]))
add(
    "round_trip_jfk_lax",
    filters(
        [seg(["JFK"], ["LAX"], OUT), seg(["LAX"], ["JFK"], RET)],
        trip_type=TripType.ROUND_TRIP,
    ),
)

rt_selected = filters(
    [seg(["JFK"], ["LHR"], OUT), seg(["LHR"], ["JFK"], RET)],
    trip_type=TripType.ROUND_TRIP,
)
rt_selected.flight_segments[0].selected_flight = selected_flight()
add("round_trip_selected_outbound", rt_selected)

rt_conn = filters(
    [seg(["JFK"], ["LHR"], OUT), seg(["LHR"], ["JFK"], RET)],
    trip_type=TripType.ROUND_TRIP,
)
rt_conn.flight_segments[0].selected_flight = two_leg_selected_flight()
add("round_trip_selected_connecting_outbound", rt_conn)

add(
    "multi_airport",
    filters([seg(["BOM", "DEL", "AMD"], ["ORD", "DTW"], MULTI)]),
)

# --- cabins --------------------------------------------------------------
for name, cabin in [
    ("economy", SeatType.ECONOMY),
    ("premium_economy", SeatType.PREMIUM_ECONOMY),
    ("business", SeatType.BUSINESS),
    ("first", SeatType.FIRST),
]:
    add(f"cabin_{name}", filters([seg(["JFK"], ["LAX"], OUT)], seat_type=cabin))

# --- stops ---------------------------------------------------------------
for name, stops in [
    ("any", MaxStops.ANY),
    ("non_stop", MaxStops.NON_STOP),
    ("one_stop_or_fewer", MaxStops.ONE_STOP_OR_FEWER),
    ("two_or_fewer_stops", MaxStops.TWO_OR_FEWER_STOPS),
]:
    add(f"stops_{name}", filters([seg(["JFK"], ["LAX"], OUT)], stops=stops))

# --- passenger mixes -----------------------------------------------------
passenger_mixes = {
    "pax_single_adult": {"adults": 1},
    "pax_two_adults": {"adults": 2},
    "pax_adult_child": {"adults": 1, "children": 1},
    "pax_adult_lap_infant": {"adults": 1, "infants_on_lap": 1},
    "pax_adult_seat_infant": {"adults": 1, "infants_in_seat": 1},
    "pax_family_mix": {"adults": 2, "children": 1, "infants_in_seat": 1, "infants_on_lap": 1},
    "pax_full_house": {"adults": 4, "children": 2, "infants_in_seat": 2, "infants_on_lap": 1},
    "pax_two_adults_two_lap_infants": {"adults": 2, "infants_on_lap": 2},
}
for name, counts in passenger_mixes.items():
    add(
        name,
        filters([seg(["JFK"], ["LAX"], OUT)], passenger_info=PassengerInfo(**counts)),
    )

# --- alliances -----------------------------------------------------------
for name, alliance in [
    ("oneworld", Alliance.ONEWORLD),
    ("skyteam", Alliance.SKYTEAM),
    ("star_alliance", Alliance.STAR_ALLIANCE),
]:
    spec = filters([seg(["JFK"], ["LAX"], OUT)])
    spec.alliances = [alliance]
    add(f"alliance_include_{name}", spec)

    spec = filters([seg(["JFK"], ["LAX"], OUT)])
    spec.alliances_exclude = [alliance]
    add(f"alliance_exclude_{name}", spec)

spec = filters([seg(["JFK"], ["LAX"], OUT)])
spec.alliances = [Alliance.ONEWORLD, Alliance.STAR_ALLIANCE]
spec.alliances_exclude = [Alliance.SKYTEAM]
add("alliance_include_two_exclude_one", spec)

# --- layovers ------------------------------------------------------------
spec = filters([seg(["JFK"], ["LAX"], OUT)])
spec.layover_restrictions = LayoverRestrictions(airports=[Airport.ORD], min_duration=120)
add("layover_airport_and_min", spec)

spec = filters([seg(["JFK"], ["LAX"], OUT)])
spec.layover_restrictions = LayoverRestrictions(max_duration=300)
add("layover_max_only", spec)

spec = filters([seg(["JFK"], ["LAX"], OUT)])
spec.layover_restrictions = LayoverRestrictions(
    airports=[Airport.ORD, Airport.DFW], min_duration=90, max_duration=600
)
add("layover_full", spec)

# --- combined ------------------------------------------------------------
spec = filters(
    [seg(["JFK", "EWR"], ["LHR", "LGW"], OUT), seg(["LHR", "LGW"], ["JFK", "EWR"], RET)],
    trip_type=TripType.ROUND_TRIP,
    stops=MaxStops.ONE_STOP_OR_FEWER,
    seat_type=SeatType.BUSINESS,
    passenger_info=PassengerInfo(adults=2, children=1, infants_on_lap=1),
)
spec.alliances = [Alliance.ONEWORLD]
spec.layover_restrictions = LayoverRestrictions(
    airports=[Airport.DUB], min_duration=60, max_duration=240
)
add("kitchen_sink_round_trip", spec)

# --- travel_dates override (date sweep) ----------------------------------
add(
    "sweep_one_way_date_override",
    filters([seg(["JFK"], ["LAX"], OUT)]),
    travel_dates=["2030-11-02"],
)
rt_sweep = filters(
    [seg(["JFK"], ["LAX"], OUT), seg(["LAX"], ["JFK"], RET)],
    trip_type=TripType.ROUND_TRIP,
)
add(
    "sweep_round_trip_date_override",
    rt_sweep,
    travel_dates=["2030-11-02", "2030-11-09"],
)

print(json.dumps(cases, indent=2, sort_keys=True))
