#!/usr/bin/env python3
"""Hotel budget finder example.

This example demonstrates how to find the best-rated hotels
within a budget threshold, combining sorting with client-side
filtering for optimal results.
"""

from datetime import datetime, timedelta

from fli.search.hotels import SearchHotels


def main():
    check_in = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    check_out = (datetime.now() + timedelta(days=34)).strftime("%Y-%m-%d")
    budget_per_night = 150.0

    search = SearchHotels()
    hotels = search.search(
        location="Barcelona",
        check_in_date=check_in,
        check_out_date=check_out,
        adults=2,
        currency="USD",
        sort_by="rating",
    )

    if not hotels:
        print("No hotels found.")
        return

    # Filter to hotels within budget
    affordable = [h for h in hotels if h.price <= budget_per_night]

    print(f"Hotels in Barcelona under ${budget_per_night}/night")
    print(f"Dates: {check_in} to {check_out} (4 nights)")
    print(f"Found {len(affordable)} of {len(hotels)} hotels within budget:\n")

    if not affordable:
        print("No hotels found within budget.")
        cheapest = min(hotels, key=lambda h: h.price)
        print(f"Cheapest available: {cheapest.name} at ${cheapest.price}/night")
        return

    # Already sorted by rating from the API
    for i, hotel in enumerate(affordable, 1):
        rating_str = f"{hotel.rating}/5" if hotel.rating else "N/A"
        total = hotel.price * 4
        print(f"{i}. {hotel.name}")
        print(f"   ${hotel.price}/night (${total:.2f} total) | Rating: {rating_str}")
        if hotel.amenities:
            print(f"   Amenities: {', '.join(hotel.amenities[:4])}")
        print()


if __name__ == "__main__":
    main()
