#!/usr/bin/env python3
"""Advanced filtering: alliances, exclusions, layovers, and locale.

This example pulls together the filters that are easy to miss:

* restrict to an airline **alliance** while **excluding** a specific carrier,
* bound layover duration and total trip duration,
* return prices in a non-USD currency for a specific language/country.

Currency, language, and country are passed to ``search()`` (they map to
Google's ``curr`` / ``hl`` / ``gl`` URL params), not to the filter object.
"""

from datetime import datetime, timedelta

from fli.models import (
    Airline,
    Airport,
    Alliance,
    FlightSearchFilters,
    FlightSegment,
    LayoverRestrictions,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.search import SearchFlights


def main():
    filters = FlightSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.NRT, 0]],
                travel_date=(datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d"),
            )
        ],
        seat_type=SeatType.BUSINESS,
        stops=MaxStops.ONE_STOP_OR_FEWER,
        alliances=[Alliance.ONEWORLD],  # only Oneworld carriers...
        airlines_exclude=[Airline.AA],  # ...but skip American
        layover_restrictions=LayoverRestrictions(min_duration=60, max_duration=240),
        max_duration=1200,  # 20 hours door-to-door, in minutes
        sort_by=SortBy.DURATION,
    )

    search = SearchFlights()
    flights = search.search(filters, currency="EUR", language="en-GB", country="GB")

    if not flights:
        print("No flights matched the filters.")
        return

    print(f"Found {len(flights)} flights (prices in EUR):\n")
    for flight in flights[:10]:
        carriers = " / ".join(sorted({leg.airline.value for leg in flight.legs}))
        print(
            f"  €{flight.price:<7.0f} {flight.duration:>4} min  "
            f"{flight.stops} stop(s)  via {carriers}"
        )


if __name__ == "__main__":
    main()
