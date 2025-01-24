import json
import urllib.parse
from enum import Enum

from pydantic import (
    BaseModel,
    PositiveInt,
)

from fli.models.airline import Airline
from fli.models.airport import Airport
from fli.models.google_flights.base import (
    FlightSegment,
    LayoverRestrictions,
    MaxStops,
    PassengerInfo,
    PriceLimit,
    SeatType,
    SortBy,
    TripType,
)


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
    max_duration: PositiveInt | None = None
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

            # Selected flight (to fetch return flights)
            selected_flights = None
            if self.trip_type == TripType.ROUND_TRIP and segment.selected_flight is not None:
                selected_flights = [
                    [
                        serialize(leg.departure_airport.name),
                        serialize(leg.departure_datetime.strftime("%Y-%m-%d")),
                        serialize(leg.arrival_airport.name),
                        None,
                        serialize(leg.airline.name),
                        serialize(leg.flight_number),
                    ]
                    for leg in segment.selected_flight.legs
                ]

            segment_formatted = [
                segment_filters[0],  # departure airport
                segment_filters[1],  # arrival airport
                time_filters,  # time restrictions
                serialize(self.stops.value),  # stops
                airlines_filters,  # airlines
                None,  # placeholder
                segment.travel_date,  # travel date
                [self.max_duration] if self.max_duration else None,  # max duration
                selected_flights,  # selected flight (to fetch return flights)
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
