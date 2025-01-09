from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from fli.app.utils import format_enum
from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.search.dates import SearchDates
from fli.search.flights import SearchFlights, SearchFlightsFilters

# Set page config
st.set_page_config(page_title="Fli", page_icon=":airplane:", layout="wide")

# Add title and description
st.title("✈️ Fli")
st.markdown("""
Search for flights using Google Flights data. 
Enter your travel details below to find available flights.
""")

# Create first row of inputs
col1, col2, col3 = st.columns(3)

with col1:
    # Origin airport
    departure_airport = st.selectbox(
        "From",
        options=list(Airport),
        format_func=lambda x: f"{x.name} ({x.value})",
        index=list(Airport).index(Airport.SFO),
    )

with col2:
    # Destination airport
    arrival_airport = st.selectbox(
        "To",
        options=list(Airport),
        format_func=lambda x: f"{x.name} ({x.value})",
        index=list(Airport).index(Airport.JFK),
    )

with col3:
    # Departure date
    min_date = datetime.now().date()
    max_date = min_date + timedelta(days=365)
    default_date = min_date + timedelta(days=30)
    departure_date = st.date_input(
        "Departure Date", min_value=min_date, max_value=max_date, value=default_date
    )

# Create second row of inputs
col4, col5, col6 = st.columns(3)

with col4:
    # Maximum stops
    stops = st.selectbox("Maximum Stops", options=list(MaxStops), format_func=format_enum)

with col5:
    # Seat type
    seat_type = st.selectbox("Cabin Class", options=list(SeatType), format_func=format_enum)

with col6:
    # Number of passengers
    num_adults = st.number_input("Number of Adults", min_value=1, max_value=9, value=1)

# Sort criteria
sort_by = st.selectbox("Sort Results By", options=list(SortBy), format_func=format_enum)

# Search button
if st.button("Search Flights", type="primary"):
    # Input validation
    if departure_airport == arrival_airport:
        st.error("Origin and destination airports cannot be the same.")
    else:
        try:
            # Create search filters
            filters = SearchFlightsFilters(
                departure_airport=departure_airport,
                arrival_airport=arrival_airport,
                departure_date=departure_date.strftime("%Y-%m-%d"),
                passenger_info=PassengerInfo(adults=num_adults),
                seat_type=seat_type,
                stops=stops,
                sort_by=sort_by,
            )

            # Show searching message
            with st.spinner("Searching for flights..."):
                # Perform search
                search = SearchFlights()
                results = search.search(filters)

                # Search for date prices (4 weeks before and after)
                date_from = departure_date - timedelta(weeks=4)
                date_to = departure_date + timedelta(weeks=4)

                date_filters = DateSearchFilters(
                    departure_airport=departure_airport,
                    arrival_airport=arrival_airport,
                    from_date=date_from.strftime("%Y-%m-%d"),
                    to_date=date_to.strftime("%Y-%m-%d"),
                    passenger_info=PassengerInfo(adults=num_adults),
                    seat_type=seat_type,
                    stops=stops,
                    flight_segments=[
                        FlightSegment(
                            departure_airport=[[departure_airport, 0]],
                            arrival_airport=[[arrival_airport, 0]],
                            travel_date=date_from.strftime("%Y-%m-%d"),
                        )
                    ],
                )

                date_search = SearchDates()
                date_results = date_search.search(date_filters)

            if results:
                # Convert results to DataFrame for better display
                flights_data = []
                for flight in results:
                    for leg in flight.legs:
                        flights_data.append(
                            {
                                "Airline": leg.airline.value,
                                "Flight": leg.flight_number,
                                "From": leg.departure_airport.value,
                                "To": leg.arrival_airport.value,
                                "Departure": leg.departure_datetime.strftime("%H:%M"),
                                "Arrival": leg.arrival_datetime.strftime("%H:%M"),
                                "Duration": f"{leg.duration} mins",
                                "Price": f"${flight.price:,.2f}",
                                "Stops": flight.stops,
                            }
                        )

                df = pd.DataFrame(flights_data)

                # Display results in a nice table
                st.subheader(f"Found {len(results)} flights")
                st.dataframe(
                    df,
                    column_config={
                        "Airline": st.column_config.TextColumn("Airline"),
                        "Flight": st.column_config.TextColumn("Flight #"),
                        "From": st.column_config.TextColumn("From"),
                        "To": st.column_config.TextColumn("To"),
                        "Departure": st.column_config.TextColumn("Departure"),
                        "Arrival": st.column_config.TextColumn("Arrival"),
                        "Duration": st.column_config.TextColumn("Duration"),
                        "Price": st.column_config.TextColumn("Price"),
                        "Stops": st.column_config.NumberColumn("Stops"),
                    },
                    hide_index=True,
                    use_container_width=True,
                )

                # Display price trend chart
                if date_results:
                    st.subheader("Price Trends")
                    date_prices = {result.date.date(): result.price for result in date_results}

                    df_prices = pd.DataFrame(
                        list(date_prices.items()), columns=["Date", "Price"]
                    ).set_index("Date")

                    st.line_chart(df_prices, use_container_width=True)

                    # Show min/max prices
                    min_price = min(date_prices.values())
                    max_price = max(date_prices.values())
                    min_date = min(date_prices.items(), key=lambda x: x[1])[0]

                    st.info(
                        "💰 Lowest price: ${:,.2f} on {}".format(
                            min_price, min_date.strftime("%B %d, %Y")
                        )
                    )
                    st.info(
                        "📈 Highest price: ${:,.2f} on {}".format(
                            max_price,
                            max(date_prices.items(), key=lambda x: x[1])[0].strftime("%B %d, %Y"),
                        )
                    )
            else:
                st.warning(
                    "No flights found for the selected criteria. Try different dates or airports."
                )
        except Exception as e:
            st.error(f"An error occurred while searching for flights: {str(e)}")
