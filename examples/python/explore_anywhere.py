"""Explore search: find the cheapest destinations from an origin.

Uses Google Flights Explore to answer "where can I fly cheaply?" — one
request returns dozens of destinations with their cheapest fares.
"""

from datetime import datetime, timedelta

from fli.models import Airport, ExploreRegion, ExploreSearchFilters
from fli.search import SearchExplore


def main() -> None:
    """Search for the cheapest places to fly from London to anywhere in Europe."""
    departure_date = (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d")

    filters = ExploreSearchFilters(
        origin=Airport.LHR,
        destination=ExploreRegion.EUROPE,  # or ANYWHERE, ASIA, a raw ExplorePlace mid...
        departure_date=departure_date,
    )

    result = SearchExplore().search(filters, currency="GBP")
    if result is None:
        print("Search failed")
        return

    priced = sorted(
        (d for d in result.destinations if d.price is not None),
        key=lambda d: d.price,
    )
    print(
        f"{len(result.destinations)} destinations from {result.origin_name} "
        f"on {departure_date} ({len(priced)} priced)\n"
    )
    for destination in priced[:10]:
        print(
            f"{destination.name:15} {destination.country or '':15} "
            f"£{destination.price:>6.0f}  {destination.airline_name or destination.airline}"
            f" -> {destination.destination_airport}"
            f" ({destination.stops} stops, {destination.duration_minutes} min)"
        )


if __name__ == "__main__":
    main()
