#!/usr/bin/env python3
"""Hotel comparison across multiple cities.

This example demonstrates how to search for hotels across multiple
destinations and compare prices side-by-side, useful for planning
a multi-city trip.
"""

from datetime import datetime, timedelta

from fli.search.hotels import SearchHotels


def main():
    check_in = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
    check_out = (datetime.now() + timedelta(days=65)).strftime("%Y-%m-%d")

    cities = ["Lima", "Buenos Aires", "Santiago"]
    search = SearchHotels()

    city_results = {}
    for city in cities:
        hotels = search.search(
            location=city,
            check_in_date=check_in,
            check_out_date=check_out,
            adults=2,
            sort_by="price",
            limit=3,
        )
        city_results[city] = hotels or []

    # Compare cheapest options across cities
    print(f"Hotel Price Comparison ({check_in} to {check_out}, 5 nights)")
    print("=" * 60)

    for city, hotels in city_results.items():
        print(f"\n📍 {city}:")
        if not hotels:
            print("   No hotels found.")
            continue

        for i, hotel in enumerate(hotels, 1):
            rating_str = f" ({hotel.rating}/5)" if hotel.rating else ""
            print(f"   {i}. {hotel.name} — ${hotel.price}/night{rating_str}")

    # Summary: cheapest option per city
    print("\n" + "=" * 60)
    print("Cheapest per city:")
    for city, hotels in city_results.items():
        if hotels:
            cheapest = min(hotels, key=lambda h: h.price)
            print(f"  {city}: {cheapest.name} at ${cheapest.price}/night")


if __name__ == "__main__":
    main()
