#!/usr/bin/env python3
"""Custom result processing and analysis example.

This example demonstrates how to process flight search results
and convert them to different formats for analysis.
"""

from datetime import datetime, timedelta

from fli.models import (
    Airport,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
)
from fli.search import SearchFlights

# Note: Install pandas with: pip install pandas
try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("Warning: pandas not installed. Install with: pip install pandas")


def analyze_results(results: list[FlightResult]) -> dict:
    """Convert results to dictionary format for analysis."""
    flights_data = []

    for flight in results:
        for leg in flight.legs:
            flights_data.append(
                {
                    "price": flight.price,
                    "total_duration": flight.duration,
                    "stops": flight.stops,
                    "airline": leg.airline.value,
                    "flight_number": leg.flight_number,
                    "departure_airport": leg.departure_airport.value,
                    "arrival_airport": leg.arrival_airport.value,
                    "departure_time": leg.departure_datetime,
                    "arrival_time": leg.arrival_datetime,
                    "leg_duration": leg.duration,
                }
            )

    return flights_data


def analyze_results_pandas(results: list[FlightResult]):
    """Convert results to pandas DataFrame for advanced analysis."""
    if not PANDAS_AVAILABLE:
        print("Pandas not available. Install with: pip install pandas")
        return None

    flights_data = analyze_results(results)
    df = pd.DataFrame(flights_data)

    print("=== Flight Analysis with Pandas ===")
    print(f"Total flights analyzed: {len(df)}")
    print("\nPrice statistics:")
    print(df["price"].describe())

    print("\nAirlines distribution:")
    print(df["airline"].value_counts())

    print("\nAverage duration by airline:")
    print(df.groupby("airline")["total_duration"].mean().sort_values())

    return df


def analyze_results_basic(results: list[FlightResult]):
    """Basic analysis without external dependencies."""
    print("=== Basic Flight Analysis ===")
    print(f"Total flights: {len(results)}")

    # Price analysis
    prices = [flight.price for flight in results]
    if prices:
        print(f"Price range: ${min(prices):.2f} - ${max(prices):.2f}")
        print(f"Average price: ${sum(prices) / len(prices):.2f}")

    # Airline analysis
    airlines = {}
    for flight in results:
        for leg in flight.legs:
            airline = leg.airline.value
            airlines[airline] = airlines.get(airline, 0) + 1

    print("\nAirlines found:")
    for airline, count in sorted(airlines.items(), key=lambda x: x[1], reverse=True):
        print(f"  {airline}: {count} flights")

    # Duration analysis
    durations = [flight.duration for flight in results]
    if durations:
        print(f"\nDuration range: {min(durations)} - {max(durations)} minutes")
        print(f"Average duration: {sum(durations) / len(durations):.1f} minutes")


def main():
    """Demonstrate result processing capabilities."""
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

    # Search for flights
    search = SearchFlights()
    results = search.search(filters)

    if not results:
        print("No flights found for analysis")
        return

    # Basic analysis
    analyze_results_basic(results)

    # Advanced analysis with pandas (if available)
    if PANDAS_AVAILABLE:
        print("\n" + "=" * 50)
        df = analyze_results_pandas(results)

        # Save to CSV for further analysis
        if df is not None:
            filename = f"flight_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            df.to_csv(filename, index=False)
            print(f"\nData saved to {filename}")


if __name__ == "__main__":
    main()
