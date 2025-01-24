"""Models for interacting with Google Flights API.

This module contains all the data models used for flight searches and results.
Models are designed to match Google Flights' APIs while providing a clean pythonic interface.
"""

from datetime import datetime
from enum import Enum

from pydantic import (
    BaseModel,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    ValidationInfo,
    field_validator,
    model_validator,
)

from fli.models.airline import Airline
from fli.models.airport import Airport


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
    """Type of flight journey."""

    ROUND_TRIP = 1
    ONE_WAY = 2

    # Currently not supported - kept for reference
    _MULTI_CITY = 3  # Unsupported


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

    @field_validator("latest_departure", "latest_arrival")
    @classmethod
    def validate_latest_times(
        cls, v: PositiveInt | None, info: ValidationInfo
    ) -> PositiveInt | None:
        """Validate and adjust the latest time restrictions."""
        if v is None:
            return v

        # Get "departure" or "arrival" from field name
        field_prefix = "earliest_" + info.field_name[7:]
        earliest = info.data.get(field_prefix)

        # Swap values to ensure that `from` is always before `to`
        if earliest is not None and earliest > v:
            info.data[field_prefix] = v
            return earliest
        return v


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
    selected_flight: FlightResult | None = None

    @property
    def parsed_travel_date(self) -> datetime:
        """Parse the travel date string into a datetime object."""
        return datetime.strptime(self.travel_date, "%Y-%m-%d")

    @field_validator("travel_date")
    @classmethod
    def validate_travel_date(cls, v: str) -> str:
        """Validate that the travel date is not in the past."""
        travel_date = datetime.strptime(v, "%Y-%m-%d").date()
        if travel_date < datetime.now().date():
            raise ValueError("Travel date cannot be in the past")
        return v

    @model_validator(mode="after")
    def validate_airports(self) -> "FlightSegment":
        """Validate that departure and arrival airports are different."""
        if not self.departure_airport or not self.arrival_airport:
            raise ValueError("Both departure and arrival airports must be specified")

        # Get first airport from each nested list
        dep_airport = (
            self.departure_airport[0][0]
            if isinstance(self.departure_airport[0][0], Airport)
            else None
        )
        arr_airport = (
            self.arrival_airport[0][0] if isinstance(self.arrival_airport[0][0], Airport) else None
        )

        if dep_airport and arr_airport and dep_airport == arr_airport:
            raise ValueError("Departure and arrival airports must be different")
        return self
