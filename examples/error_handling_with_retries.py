#!/usr/bin/env python3
"""Error handling and retry logic example.

This example demonstrates how to handle rate limits and implement
retry logic for robust flight searching.
"""

from datetime import datetime, timedelta

from fli.models import Airport, FlightSearchFilters, FlightSegment, PassengerInfo
from fli.search import SearchFlights

# Note: Install tenacity with: pip install tenacity
try:
    from tenacity import retry, stop_after_attempt, wait_exponential

    TENACITY_AVAILABLE = True
except ImportError:
    TENACITY_AVAILABLE = False
    print("Warning: tenacity not installed. Install with: pip install tenacity")


def simple_retry_search(filters: FlightSearchFilters, max_attempts=3):
    """Simple retry logic without external dependencies."""
    search = SearchFlights()

    for attempt in range(max_attempts):
        try:
            print(f"Attempt {attempt + 1}/{max_attempts}")
            results = search.search(filters)
            if not results:
                raise ValueError("No results found")
            return results
        except Exception as e:
            print(f"Search failed: {str(e)}")
            if attempt == max_attempts - 1:  # Last attempt
                raise
            print("Retrying...")

    return None


if TENACITY_AVAILABLE:

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=60))
    def search_with_retry(filters: FlightSearchFilters):
        """Advanced retry logic with exponential backoff."""
        search = SearchFlights()
        try:
            results = search.search(filters)
            if not results:
                raise ValueError("No results found")
            return results
        except Exception as e:
            print(f"Search failed: {str(e)}")
            raise  # Retry will handle this


def main():
    """Demonstrate error handling approaches."""
    # Create search filters
    filters = FlightSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            )
        ],
    )

    print("=== Simple Retry Example ===")
    try:
        results = simple_retry_search(filters)
        print(f"Success! Found {len(results)} flights")
        for i, flight in enumerate(results[:3], 1):  # Show first 3 results
            print(f"  Flight {i}: ${flight.price}")
    except Exception as e:
        print(f"All retry attempts failed: {e}")

    if TENACITY_AVAILABLE:
        print("\n=== Advanced Retry with Tenacity ===")
        try:
            results = search_with_retry(filters)
            print(f"Success! Found {len(results)} flights")
            for i, flight in enumerate(results[:3], 1):  # Show first 3 results
                print(f"  Flight {i}: ${flight.price}")
        except Exception as e:
            print(f"All retry attempts failed: {e}")
    else:
        print("\n=== Advanced Retry (Tenacity not available) ===")
        print("Install tenacity to use advanced retry features: pip install tenacity")


if __name__ == "__main__":
    main()
