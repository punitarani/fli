#!/usr/bin/env python3
"""Basic hotel search example.

This example demonstrates how to search for hotels in a city
with default options using the most basic configuration.
"""

from datetime import datetime, timedelta

from fli.search.hotels import SearchHotels


def main():
    # Calculate dates 30 days from now, 3-night stay
    check_in = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    check_out = (datetime.now() + timedelta(days=33)).strftime("%Y-%m-%d")

    # Search for hotels
    search = SearchHotels()
    hotels = search.search(
        location="Lima",
        check_in_date=check_in,
        check_out_date=check_out,
    )

    if not hotels:
        print("No hotels found.")
        return

    # Display results
    print(f"Found {len(hotels)} hotels in Lima ({check_in} to {check_out}):\n")
    for i, hotel in enumerate(hotels, 1):
        print(f"{i}. {hotel.name}")
        print(f"   Price: ${hotel.price}/night")
        if hotel.rating:
            print(f"   Rating: {hotel.rating}/5")
        if hotel.amenities:
            print(f"   Amenities: {', '.join(hotel.amenities[:3])}")
        print()


if __name__ == "__main__":
    main()
