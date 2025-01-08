"""Models for interacting with Google Flights API.

This module contains all the data models used for flight searches and results.
Models are designed to match Google Flights' APIs while providing a clean pythonic interface.
"""

import json
import urllib.parse
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, NonNegativeFloat, NonNegativeInt, PositiveInt

from .airline import Airline
from .airport import Airport


class SeatType(Enum):
    """Available cabin classes for flights."""

    ECONOMY = 1
    PREMIUM_ECONOMY = 2
    BUSINESS = 3
    FIRST = 4


class SortBy(Enum):
    """Available sorting options for flight results."""

    NONE = 0
    TOP_FLIGHTS = 1
    CHEAPEST = 2
    DEPARTURE_TIME = 3
    ARRIVAL_TIME = 4
    DURATION = 5


class TripType(Enum):
    """Type of flight journey. Currently only supports one-way flights."""

    ONE_WAY = 2

    # Currently not supported - kept for future reference
    _ROUND_TRIP = 1  # Deprecated
    _MULTI_CITY = 3  # Deprecated


class MaxStops(Enum):
    """Maximum number of stops allowed in flight search."""

    ANY = 0
    NON_STOP = 1
    ONE_STOP_OR_FEWER = 2
    TWO_OR_FEWER_STOPS = 3


class Currency(Enum):
    """Supported currencies for pricing. Currently only USD."""

    USD = "USD"
    # Placeholder for other currencies


class TimeRestrictions(BaseModel):
    """Time constraints for flight departure and arrival in local time.

    All times are in hours from midnight (e.g., 20 = 8:00 PM).
    """

    earliest_departure: NonNegativeInt | None = None
    latest_departure: PositiveInt | None = None
    earliest_arrival: NonNegativeInt | None = None
    latest_arrival: PositiveInt | None = None


class PassengerInfo(BaseModel):
    """Passenger configuration for flight search."""

    adults: NonNegativeInt = 1
    children: NonNegativeInt = 0
    infants_in_seat: NonNegativeInt = 0
    infants_on_lap: NonNegativeInt = 0


class PriceLimit(BaseModel):
    """Maximum price constraint for flight search."""

    max_price: PositiveInt
    currency: Currency | None = Currency.USD


class LayoverRestrictions(BaseModel):
    """Constraints for layovers in multi-leg flights."""

    airports: list[Airport] | None = None
    max_duration: PositiveInt | None = None


class FlightSegment(BaseModel):
    """A segment represents a single portion of a flight journey between two airports.

    For example, in a one-way flight from JFK to LAX, there would be one segment.
    In a multi-city trip from JFK -> LAX -> SEA, there would be two segments:
    JFK -> LAX and LAX -> SEA.
    """

    departure_airport: list[list[Airport | int]]
    arrival_airport: list[list[Airport | int]]
    travel_date: str
    time_restrictions: TimeRestrictions | None = None


class FlightLeg(BaseModel):
    """A single flight leg (segment) with airline and timing details."""

    airline: Airline
    flight_number: str
    departure_airport: Airport
    arrival_airport: Airport
    departure_datetime: datetime
    arrival_datetime: datetime
    duration: PositiveInt  # in minutes


class FlightResult(BaseModel):
    """Complete flight search result with pricing and timing."""

    legs: list[FlightLeg]
    price: NonNegativeFloat  # in specified currency
    duration: PositiveInt  # total duration in minutes
    stops: NonNegativeInt


class FlightSearchFilters(BaseModel):
    """Complete set of filters for flight search.

    This model matches required Google Flights' API structure.
    """

    trip_type: TripType = TripType.ONE_WAY
    passenger_info: PassengerInfo
    flight_segments: list[FlightSegment]
    stops: MaxStops = MaxStops.ANY
    seat_type: SeatType = SeatType.ECONOMY
    price_limit: PriceLimit | None = None
    airlines: list[Airline] | None = None
    max_duration: PositiveInt | None = None  # in minutes
    layover_restrictions: LayoverRestrictions | None = None
    sort_by: SortBy = SortBy.NONE

    def format(self) -> list:
        """Format filters into Google Flights API structure.

        This method converts the FlightSearchFilters model into the specific nested list/dict
        structure required by Google Flights' API.

        The output format matches Google Flights' internal API structure, with careful handling
        of nested arrays and proper serialization of enums and model objects.

        Returns:
            list: A formatted list structure ready for the Google Flights API request

        """

        def serialize(obj):
            if isinstance(obj, Airport) or isinstance(obj, Airline):
                return obj.name
            if isinstance(obj, Enum):
                return obj.value
            if isinstance(obj, list):
                return [serialize(item) for item in obj]
            if isinstance(obj, dict):
                return {key: serialize(value) for key, value in obj.items()}
            if isinstance(obj, BaseModel):
                return serialize(obj.dict(exclude_none=True))
            return obj

        # Format flight segments
        formatted_segments = []
        for segment in self.flight_segments:
            # Format airport codes with correct nesting
            segment_filters = [
                [
                    [
                        [serialize(airport[0]), serialize(airport[1])]
                        for airport in segment.departure_airport
                    ]
                ],
                [
                    [
                        [serialize(airport[0]), serialize(airport[1])]
                        for airport in segment.arrival_airport
                    ]
                ],
            ]

            # Time restrictions
            if segment.time_restrictions:
                time_filters = [
                    segment.time_restrictions.earliest_departure,
                    segment.time_restrictions.latest_departure,
                    segment.time_restrictions.earliest_arrival,
                    segment.time_restrictions.latest_arrival,
                ]
            else:
                time_filters = None

            # Airlines
            airlines_filters = None
            if self.airlines:
                sorted_airlines = sorted(self.airlines, key=lambda x: x.value)
                airlines_filters = [serialize(airline) for airline in sorted_airlines]

            # Layover restrictions
            layover_airports = (
                [serialize(a) for a in self.layover_restrictions.airports]
                if self.layover_restrictions and self.layover_restrictions.airports
                else None
            )
            layover_duration = (
                self.layover_restrictions.max_duration if self.layover_restrictions else None
            )

            segment_formatted = [
                segment_filters[0],  # departure airport
                segment_filters[1],  # arrival airport
                time_filters,  # time restrictions
                serialize(self.stops.value),  # stops
                airlines_filters,  # airlines
                None,  # placeholder
                segment.travel_date,  # travel date
                [self.max_duration] if self.max_duration else None,  # max duration
                None,  # placeholder
                layover_airports,  # layover airports
                None,  # placeholder
                None,  # placeholder
                layover_duration,  # layover duration
                None,  # emissions
                3,  # constant value
            ]
            formatted_segments.append(segment_formatted)

        # Create the main filters structure
        filters = [
            [],  # empty array at start
            [
                None,  # placeholder
                None,  # placeholder
                serialize(self.trip_type.value),
                None,  # placeholder
                [],  # empty array
                serialize(self.seat_type.value),
                [
                    self.passenger_info.adults,
                    self.passenger_info.children,
                    self.passenger_info.infants_on_lap,
                    self.passenger_info.infants_in_seat,
                ],
                [None, self.price_limit.max_price] if self.price_limit else None,
                None,  # placeholder
                None,  # placeholder
                None,  # placeholder
                None,  # placeholder
                None,  # placeholder
                formatted_segments,
                None,  # placeholder
                None,  # placeholder
                None,  # placeholder
                1,  # placeholder (hardcoded to 1)
            ],
            serialize(self.sort_by.value),
            0,  # constant
            0,  # constant
            2,  # constant
        ]

        return filters

    def encode(self) -> str:
        """URL encode the formatted filters for API request."""
        formatted_filters = self.format()
        # First convert the formatted filters to a JSON string
        formatted_json = json.dumps(formatted_filters, separators=(",", ":"))
        # Then wrap it in a list with null
        wrapped_filters = [None, formatted_json]
        # Finally, encode the whole thing
        return urllib.parse.quote(json.dumps(wrapped_filters, separators=(",", ":")))


class DateSearchFilters(BaseModel):
    """Filters for searching flights across a date range.

    Similar to FlightSearchFilters but includes date range parameters
    for finding the cheapest dates to fly.
    """

    trip_type: TripType = TripType.ONE_WAY
    passenger_info: PassengerInfo
    flight_segments: list[FlightSegment]
    stops: MaxStops = MaxStops.ANY
    seat_type: SeatType = SeatType.ECONOMY
    price_limit: PriceLimit | None = None
    airlines: list[Airline] | None = None
    max_duration: PositiveInt | None = None  # in minutes
    layover_restrictions: LayoverRestrictions | None = None
    from_date: str  # YYYY-MM-DD format
    to_date: str  # YYYY-MM-DD format

    def format(self) -> list:
        """Format filters into Google Flights API structure.

        This method converts the DateSearchFilters model into the specific nested list/dict
        structure required by Google Flights' API.

        Returns:
            list: A formatted list structure ready for the Google Flights API request

        """

        def serialize(obj):
            if isinstance(obj, Airport) or isinstance(obj, Airline):
                return obj.name
            if isinstance(obj, Enum):
                return obj.value
            if isinstance(obj, list):
                return [serialize(item) for item in obj]
            if isinstance(obj, dict):
                return {key: serialize(value) for key, value in obj.items()}
            if isinstance(obj, BaseModel):
                return serialize(obj.dict(exclude_none=True))
            return obj

        # Format flight segments
        formatted_segments = []
        for segment in self.flight_segments:
            # Format airport codes with correct nesting
            segment_filters = [
                [
                    [
                        [serialize(airport[0]), serialize(airport[1])]
                        for airport in segment.departure_airport
                    ]
                ],
                [
                    [
                        [serialize(airport[0]), serialize(airport[1])]
                        for airport in segment.arrival_airport
                    ]
                ],
            ]

            # Time restrictions
            if segment.time_restrictions:
                time_filters = [
                    segment.time_restrictions.earliest_departure,
                    segment.time_restrictions.latest_departure,
                    segment.time_restrictions.earliest_arrival,
                    segment.time_restrictions.latest_arrival,
                ]
            else:
                time_filters = None

            # Airlines
            airlines_filters = None
            if self.airlines:
                sorted_airlines = sorted(self.airlines, key=lambda x: x.value)
                airlines_filters = [serialize(airline) for airline in sorted_airlines]

            # Layover restrictions
            layover_airports = (
                [serialize(a) for a in self.layover_restrictions.airports]
                if self.layover_restrictions and self.layover_restrictions.airports
                else None
            )
            layover_duration = (
                self.layover_restrictions.max_duration if self.layover_restrictions else None
            )

            segment_formatted = [
                segment_filters[0],  # departure airport
                segment_filters[1],  # arrival airport
                time_filters,  # time restrictions
                serialize(self.stops.value),  # stops
                airlines_filters,  # airlines
                None,  # placeholder
                segment.travel_date,  # travel date
                [self.max_duration] if self.max_duration else None,  # max duration
                None,  # placeholder
                layover_airports,  # layover airports
                None,  # placeholder
                None,  # placeholder
                layover_duration,  # layover duration
                None,  # emissions
                3,  # constant value
            ]
            formatted_segments.append(segment_formatted)

        # Create the main filters structure
        filters = [
            None,  # placeholder
            [
                None,  # placeholder
                None,  # placeholder
                serialize(self.trip_type.value),
                None,  # placeholder
                [],  # empty array
                serialize(self.seat_type.value),
                [
                    self.passenger_info.adults,
                    self.passenger_info.children,
                    self.passenger_info.infants_on_lap,
                    self.passenger_info.infants_in_seat,
                ],
                [None, self.price_limit.max_price] if self.price_limit else None,
                None,  # placeholder
                None,  # placeholder
                None,  # placeholder
                None,  # placeholder
                None,  # placeholder
                formatted_segments,
                None,  # placeholder
                None,  # placeholder
                None,  # placeholder
                1,  # placeholder (hardcoded to 1)
            ],
            [
                serialize(self.from_date),
                serialize(self.to_date),
            ],
        ]

        return filters

    def encode(self) -> str:
        """URL encode the formatted filters for API request."""
        formatted_filters = self.format()
        # First convert the formatted filters to a JSON string
        formatted_json = json.dumps(formatted_filters, separators=(",", ":"))
        # Then wrap it in a list with null
        wrapped_filters = [None, formatted_json]
        # Finally, encode the whole thing
        return urllib.parse.quote(json.dumps(wrapped_filters, separators=(",", ":")))
