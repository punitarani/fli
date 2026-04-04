#!/usr/bin/env python3
"""Hotel multi-currency comparison example.

This example demonstrates how to search for hotels in different currencies
to compare pricing, useful for travelers deciding which currency to book in.
"""

from datetime import datetime, timedelta

from fli.search.hotels import SearchHotels


def main():
    check_in = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    check_out = (datetime.now() + timedelta(days=35)).strftime("%Y-%m-%d")

    currencies = ["USD", "EUR", "GBP"]
    currency_symbols = {"USD": "$", "EUR": "€", "GBP": "£"}

    search = SearchHotels()

    print(f"Hotel prices in London ({check_in} to {check_out})")
    print("=" * 60)

    results_by_currency = {}
    for currency in currencies:
        hotels = search.search(
            location="London",
            check_in_date=check_in,
            check_out_date=check_out,
            adults=2,
            currency=currency,
            sort_by="price",
            limit=5,
        )
        results_by_currency[currency] = hotels or []

    # Display side-by-side comparison for the cheapest hotel in each currency
    for currency, hotels in results_by_currency.items():
        symbol = currency_symbols[currency]
        print(f"\n💱 {currency}:")
        if not hotels:
            print("   No results.")
            continue

        for i, hotel in enumerate(hotels, 1):
            rating_str = f" ({hotel.rating}/5)" if hotel.rating else ""
            print(f"   {i}. {hotel.name} — {symbol}{hotel.price}/night{rating_str}")


if __name__ == "__main__":
    main()
