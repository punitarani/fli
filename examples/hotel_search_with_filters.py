#!/usr/bin/env python3
"""Hotel search with filters example.

This example demonstrates how to search for hotels with detailed filters
including guest counts, sorting, currency, and result limits.
"""

from datetime import datetime, timedelta

from fli.search.hotels import SearchHotels


def main():
    check_in = (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d")
    check_out = (datetime.now() + timedelta(days=52)).strftime("%Y-%m-%d")

    # Search with all available filters
    search = SearchHotels()
    hotels = search.search(
        location="Tokyo",
        check_in_date=check_in,
        check_out_date=check_out,
        adults=2,
        children=1,
        currency="EUR",
        sort_by="rating",
        limit=10,
    )

    if not hotels:
        print("No hotels found.")
        return

    print(f"Top {len(hotels)} hotels in Tokyo (sorted by rating):\n")
    for i, hotel in enumerate(hotels, 1):
        rating_str = f"{hotel.rating}/5" if hotel.rating else "N/A"
        print(f"{i}. {hotel.name}")
        print(f"   Price: €{hotel.price}/night | Rating: {rating_str}")
        if hotel.amenities:
            print(f"   Amenities: {', '.join(hotel.amenities[:5])}")
        if hotel.url:
            print(f"   URL: {hotel.url}")
        print()


if __name__ == "__main__":
    main()
