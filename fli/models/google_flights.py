import json
import urllib.parse
from datetime import datetime
from enum import Enum
from typing import List, Optional, Union

from pydantic import BaseModel, PositiveInt

from .airline import Airline
from .airport import Airport


class SeatType(Enum):
    ECONOMY = 1
    PREMIUM_ECONOMY = 2
    BUSINESS = 3
    FIRST = 4


class SortBy(Enum):
    NONE = 0
    TOP_FLIGHTS = 1
    CHEAPEST = 2
    DEPARTURE_TIME = 3
    ARRIVAL_TIME = 4
    DURATION = 5


class TripType(Enum):
    ONE_WAY = 2

    # Deprecated - kept for reference
    _ROUND_TRIP = 1  # Deprecated
    _MULTI_CITY = 3  # Deprecated


class MaxStops(Enum):
    ANY = 0
    NON_STOP = 1
    ONE_STOP_OR_FEWER = 2
    TWO_OR_FEWER_STOPS = 3


class Currency(Enum):
    USD = "USD"
    # Placeholder for other currencies


class TimeRestrictions(BaseModel):
    earliest_departure: Optional[int]
    latest_departure: Optional[int]
    earliest_arrival: Optional[int]
    latest_arrival: Optional[int]


class PassengerInfo(BaseModel):
    adults: int
    children: int
    infants_in_seat: int
    infants_on_lap: int


class PriceLimit(BaseModel):
    max_price: int
    currency: Optional[Currency] = Currency.USD


class LayoverRestrictions(BaseModel):
    airports: Optional[List[Airport]]
    max_duration: Optional[int]


class FlightSegment(BaseModel):
    departure_airport: List[List[Union[Airport, int]]]
    arrival_airport: List[List[Union[Airport, int]]]
    travel_date: str
    time_restrictions: Optional[TimeRestrictions] = None


class FlightLeg(BaseModel):
    airline: Airline
    flight_number: str
    departure_airport: Airport
    arrival_airport: Airport
    departure_datetime: datetime
    arrival_datetime: datetime
    duration: int


class FlightResult(BaseModel):
    legs: List[FlightLeg]
    price: float
    duration: int
    stops: int


class FlightSearchFilters(BaseModel):
    trip_type: TripType = TripType.ONE_WAY
    passenger_info: PassengerInfo
    flight_segments: List[FlightSegment]
    stops: MaxStops = MaxStops.ANY
    seat_type: SeatType = SeatType.ECONOMY
    price_limit: Optional[PriceLimit] = None
    airlines: Optional[List[Airline]] = None
    max_duration: Optional[int] = None
    layover_restrictions: Optional[LayoverRestrictions] = None
    sort_by: SortBy = SortBy.NONE

    def format(self) -> list:
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
        """Format and URL encode the filters."""
        formatted_filters = self.format()
        # First convert the formatted filters to a JSON string
        formatted_json = json.dumps(formatted_filters, separators=(",", ":"))
        # Then wrap it in a list with null
        wrapped_filters = [None, formatted_json]
        # Finally, encode the whole thing
        return urllib.parse.quote(json.dumps(wrapped_filters, separators=(",", ":")))
