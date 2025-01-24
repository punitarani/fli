import json
import urllib.parse
from datetime import datetime
from enum import Enum

from pydantic import (
    BaseModel,
    PositiveInt,
    ValidationInfo,
    field_validator,
    model_validator,
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
    TripType,
)


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
    max_duration: PositiveInt | None = None
    layover_restrictions: LayoverRestrictions | None = None
    from_date: str
    to_date: str
    duration: PositiveInt | None = None

    @property
    def parsed_from_date(self) -> datetime:
        """Parse the from_date string into a datetime object."""
        return datetime.strptime(self.from_date, "%Y-%m-%d")

    @property
    def parsed_to_date(self) -> datetime:
        """Parse the to_date string into a datetime object."""
        return datetime.strptime(self.to_date, "%Y-%m-%d")

    @field_validator("duration")
    @classmethod
    def ensure_duration_if_round_trip(
        cls, v: PositiveInt | None, info: ValidationInfo
    ) -> PositiveInt | None:
        """Ensure duration is set if trip_type is ROUND_TRIP."""
        if "trip_type" in info.data and info.data["trip_type"] == TripType.ROUND_TRIP:
            if v is None:
                raise ValueError("Duration must be set for round trip flights")
        return v

    @field_validator("flight_segments")
    @classmethod
    def ensure_correct_flight_segments(
        cls, v: list[FlightSegment], info: ValidationInfo
    ) -> list[FlightSegment]:
        """Ensure flight segments are correct."""
        # Ensure only one flight segment if trip_type is ONE_WAY
        if "trip_type" in info.data and info.data["trip_type"] == TripType.ONE_WAY:
            if len(v) != 1:
                raise ValueError("One-way trip must have one flight segment")
            return v

        # Ensure only two flight segments if trip_type is ROUND_TRIP
        if "trip_type" in info.data and info.data["trip_type"] == TripType.ROUND_TRIP:
            if len(v) != 2:
                raise ValueError("Round trip must have two flight segments")

        # Ensure the travel date difference is the same as the duration
        if "duration" in info.data and info.data["duration"] is not None:
            if len(v) == 2:
                duration = info.data["duration"]
                segment_difference = (v[1].parsed_travel_date - v[0].parsed_travel_date).days
                if duration != segment_difference:
                    raise ValueError("Flight segments travel dates difference must match duration")

        return v

    @field_validator("from_date", "to_date")
    @classmethod
    def validate_date_order(cls, v: str, info: ValidationInfo) -> str:
        """Validate and adjust the date range constraints."""
        if info.field_name == "from_date":
            # Remove the past date check since we'll handle it in model validator
            return v

        # Ensure to_date is after from_date
        if "from_date" in info.data:
            from_date = datetime.strptime(info.data["from_date"], "%Y-%m-%d").date()
            to_date = datetime.strptime(v, "%Y-%m-%d").date()
            if from_date > to_date:
                # Swap dates by returning the from_date
                info.data["from_date"] = v
                return from_date.strftime("%Y-%m-%d")
        return v

    @field_validator("to_date")
    @classmethod
    def validate_to_date(cls, v: str) -> str:
        """Validate that to_date is in the future."""
        to_date = datetime.strptime(v, "%Y-%m-%d").date()
        if to_date <= datetime.now().date():
            raise ValueError("To date must be in the future")
        return v

    @model_validator(mode="after")
    def validate_and_adjust_from_date(self) -> "DateSearchFilters":
        """Adjust from_date to current date if it's in the past."""
        from_date = self.parsed_from_date.date()
        current_date = datetime.now().date()

        if from_date < current_date:
            self.from_date = current_date.strftime("%Y-%m-%d")

        return self

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

        # Format duration filters for round trips
        if self.trip_type == TripType.ROUND_TRIP:
            duration_filters = (None, [self.duration, self.duration])
        else:
            duration_filters = ()

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
            *duration_filters,
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
