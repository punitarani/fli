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
    """Available sorting options for flight results.

    Maps to the top-level sort_mode value in the Google Flights API payload.
    """

    TOP_FLIGHTS = 0
    BEST = 1
    CHEAPEST = 2
    DEPARTURE_TIME = 3
    ARRIVAL_TIME = 4
    DURATION = 5
    EMISSIONS = 6


class TripType(Enum):
    """Type of flight journey."""

    ROUND_TRIP = 1
    ONE_WAY = 2
    MULTI_CITY = 3


class MaxStops(Enum):
    """Maximum number of stops allowed in flight search."""

    ANY = 0
    NON_STOP = 1
    ONE_STOP_OR_FEWER = 2
    TWO_OR_FEWER_STOPS = 3


class EmissionsFilter(Enum):
    """Filter flights by carbon emissions level.

    Corresponds to the "Less emissions" toggle on Google Flights.
    When enabled, only flights with lower-than-average CO2 emissions are shown.
    """

    ALL = 0
    LESS = 1


class Currency(Enum):
    """ISO 4217 currency codes accepted by Google Flights via `curr=` URL param.

    Google honours the `curr=` URL query parameter on its frontend service
    endpoints to translate prices into a requested currency. The set below
    covers the codes Google Flights' UI lets the user pick. Codes not in this
    list may still work; pass a plain string via :class:`PriceLimit.currency`
    or the search-level ``currency`` argument when calling
    :class:`fli.search.SearchFlights`.
    """

    AED = "AED"
    ARS = "ARS"
    AUD = "AUD"
    BGN = "BGN"
    BRL = "BRL"
    CAD = "CAD"
    CHF = "CHF"
    CLP = "CLP"
    CNY = "CNY"
    COP = "COP"
    CZK = "CZK"
    DKK = "DKK"
    EGP = "EGP"
    EUR = "EUR"
    GBP = "GBP"
    HKD = "HKD"
    HUF = "HUF"
    IDR = "IDR"
    ILS = "ILS"
    INR = "INR"
    JPY = "JPY"
    KRW = "KRW"
    MXN = "MXN"
    MYR = "MYR"
    NOK = "NOK"
    NZD = "NZD"
    PEN = "PEN"
    PHP = "PHP"
    PLN = "PLN"
    QAR = "QAR"
    RON = "RON"
    SAR = "SAR"
    SEK = "SEK"
    SGD = "SGD"
    THB = "THB"
    TRY = "TRY"
    TWD = "TWD"
    UAH = "UAH"
    USD = "USD"
    VND = "VND"
    ZAR = "ZAR"


class BagsFilter(BaseModel):
    """Include checked/carry-on bag fees in displayed prices.

    When set, Google Flights adjusts the displayed price to include baggage costs,
    making comparisons between budget and full-service carriers fairer.
    """

    checked_bags: NonNegativeInt = 0
    carry_on: bool = False


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


class Alliance(Enum):
    """Airline alliances accepted by Google Flights' include/exclude filters.

    Google Flights treats alliance identifiers as drop-in values inside the
    airline include (segment[4]) or exclude (segment[5]) lists. The string
    form below matches Google's accepted spelling (note ``STAR_ALLIANCE``
    requires an underscore — ``"Star Alliance"`` and ``"STAR ALLIANCE"``
    both return zero results).
    """

    ONEWORLD = "ONEWORLD"
    SKYTEAM = "SKYTEAM"
    STAR_ALLIANCE = "STAR_ALLIANCE"


class LayoverRestrictions(BaseModel):
    """Constraints for layovers in multi-leg flights.

    ``airports`` is an include list — only the listed airports may be used
    as layover stops. ``min_duration`` / ``max_duration`` bound the wait
    time between legs in minutes; either can be set independently.
    """

    airports: list[Airport] | None = None
    min_duration: PositiveInt | None = None
    max_duration: PositiveInt | None = None


class Amenities(BaseModel):
    """Per-leg amenities reported by Google Flights.

    All fields are tri-state (`True`, `False`, or `None` when Google did not
    publish that signal for the leg).
    """

    wifi: bool | None = None
    power: bool | None = None
    usb_power: bool | None = None
    in_seat_video: bool | None = None
    on_demand_video: bool | None = None
    legroom_rating: NonNegativeInt | None = None


class Layover(BaseModel):
    """Layover info between two flight legs.

    ``duration`` is the wait time at the layover airport in minutes.
    ``overnight`` is set when the layover crosses local midnight at the
    airport. ``change_of_airport`` is set when the next leg departs from a
    different airport than the previous leg arrived at (rare but supported
    by Google Flights — e.g. JFK arrival + LGA departure in NYC).

    ``city`` and ``airport_name`` are populated from Google's response when
    available (``detail[13]``); they are optional because the parser also
    derives layovers structurally from leg timestamps when the detail block
    isn't present (e.g. on captured fixtures with old responses).
    """

    airport: Airport
    duration: NonNegativeInt
    overnight: bool = False
    change_of_airport: bool = False
    city: str | None = None
    airport_name: str | None = None


class FlightLeg(BaseModel):
    """A single flight leg (segment) with airline and timing details."""

    airline: Airline
    flight_number: str
    departure_airport: Airport
    arrival_airport: Airport
    departure_datetime: datetime
    arrival_datetime: datetime
    duration: PositiveInt  # in minutes

    # Optional richer fields populated when present in Google's response.
    departure_airport_name: str | None = None
    arrival_airport_name: str | None = None
    operating_airline: Airline | None = None
    operating_flight_number: str | None = None
    aircraft: str | None = None
    legroom: str | None = None
    legroom_short: str | None = None
    amenities: Amenities | None = None
    overnight: bool = False
    co2_emissions_g: NonNegativeInt | None = None


class BookingOption(BaseModel):
    """A single bookable fare exposed by GetBookingResults.

    Google Flights' booking page surfaces a list of vendors (airline direct and
    OTAs) with per-fare prices and click-through URLs. This model captures one
    such row.
    """

    vendor_code: str | None = None
    vendor_name: str | None = None
    is_airline_direct: bool = False
    price: NonNegativeFloat | None = None
    currency: str | None = None
    fare_name: str | None = None
    booking_url: str | None = None
    google_click_url: str | None = None
    flights: list[tuple[str, str]] | None = None  # [(airline_code, flight_number), ...]


class FlightResult(BaseModel):
    """Complete flight search result with pricing and timing.

    ``price`` is ``None`` when Google did not surface a per-row aggregate
    price in the shopping response. This happens predictably for
    premium-cabin (BUSINESS / FIRST) round-trip itineraries with
    multi-passenger configs — Google expects the caller to pick a
    specific outbound+return pair and fetch real fares via
    :meth:`SearchFlights.get_booking_options`. The per-row
    ``booking_token`` is still populated in that case, so the booking
    follow-up has everything it needs.

    Downstream code that filters or sorts by price should guard against
    ``None`` — the convenience property :attr:`price_unknown` exists for
    that purpose (``if flight.price_unknown: ...`` reads more cleanly
    than ``if flight.price is None: ...``).
    """

    legs: list[FlightLeg]
    price: NonNegativeFloat | None = None  # in specified currency; None when not surfaced
    currency: str | None = None
    duration: PositiveInt  # total duration in minutes
    stops: NonNegativeInt

    # Optional richer fields populated when present in Google's response.
    layovers: list[Layover] | None = None
    co2_emissions_g: NonNegativeInt | None = None
    co2_emissions_typical_g: NonNegativeInt | None = None
    co2_emissions_delta_pct: int | None = None
    emissions_tag: str | None = None  # "lower" | "typical" | "higher"
    self_transfer: bool | None = None
    mixed_cabin: bool | None = None
    primary_airline: Airline | None = None
    primary_airline_name: str | None = None
    booking_token: str | None = None

    @property
    def price_unknown(self) -> bool:
        """``True`` when Google did not surface a price for this row.

        Equivalent to ``self.price is None`` — provided for readability
        in filtering / sorting code. Use this to skip priceless rows
        when computing aggregate statistics::

            cheapest = min(
                (f for f in flights if not f.price_unknown),
                key=lambda f: f.price,
                default=None,
            )

        See :issue:`165` for the wire-format quirk that motivates this.
        """
        return self.price is None


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
