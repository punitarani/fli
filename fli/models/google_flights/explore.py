"""Models for the Google Flights Explore (``GetExploreDestinations``) endpoint.

Explore is the https://www.google.com/travel/explore feature: search from an
origin to "Anywhere" (or a region) and get back many destinations, each with
the cheapest found fare.

Unlike the other FlightsFrontendService endpoints, Explore locations are
Google knowledge-graph entities (``/m/...`` mids) with a type code, not just
IATA codes:

    ``["JFK", 0]``        airport (same encoding as the other endpoints)
    ``["/m/04jpl", 4]``   city / metro area (London)
    ``["/m/0250wj", 6]``  region / continent (Southern Europe)

The wire format below was reverse-engineered from a HAR capture of the
Explore UI (2026-08) in which filters were toggled one at a time, isolating
every payload position; positions were cross-checked against the ``tfs=``
protobuf in each request's Referer. Slots marked "HAR-confirmed" were
observed changing in the capture; slots marked "inferred" follow the shared
FlightsFrontendService message layout (see ``DateSearchFilters.format()``)
but were not directly exercised.
"""

import json
import urllib.parse
from datetime import datetime
from enum import Enum

from pydantic import (
    BaseModel,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    field_validator,
    model_validator,
)

from fli.models.airline import Airline
from fli.models.airport import Airport
from fli.models.google_flights.base import (
    Alliance,
    BagsFilter,
    MaxStops,
    PassengerInfo,
    PriceLimit,
    SeatType,
    TripType,
)


class ExplorePlaceType(Enum):
    """Location type codes accepted by the Explore endpoint.

    ``AIRPORT`` matches the encoding used by every other fli endpoint;
    ``CITY`` and ``REGION`` were both observed in the HAR capture.
    """

    AIRPORT = 0
    CITY = 4
    REGION = 6


class ExploreRegion(Enum):
    """Curated knowledge-graph mids for well-known Explore destinations.

    ``ANYWHERE`` (``/m/02j71`` = Earth) and the continent mids come from
    Google's place autocomplete (``H028ib``); ``EUROPE`` and
    ``SOUTHERN_EUROPE`` were additionally confirmed in live Explore requests
    in the HAR capture. All values are verified live by
    ``scripts/probe_explore.py`` before release.
    """

    ANYWHERE = "/m/02j71"
    EUROPE = "/m/02j9z"
    SOUTHERN_EUROPE = "/m/0250wj"
    ASIA = "/m/0j0k"
    AFRICA = "/m/0dg3n1"
    NORTH_AMERICA = "/m/059g4"
    SOUTH_AMERICA = "/m/06n3y"
    OCEANIA = "/m/05nrg"


class ExplorePlace(BaseModel):
    """A raw knowledge-graph place for Explore origins/destinations.

    Use this to pass any Google mid not covered by :class:`ExploreRegion`
    (e.g. a city or country resolved externally). ``type_code`` follows
    :class:`ExplorePlaceType` (4 = city/metro, 6 = region/country/continent).
    """

    mid: str
    type_code: int = ExplorePlaceType.REGION.value

    @field_validator("mid")
    @classmethod
    def validate_mid(cls, v: str) -> str:
        """Ensure the mid looks like a knowledge-graph identifier."""
        if not (v.startswith("/m/") or v.startswith("/g/")):
            raise ValueError("mid must be a knowledge-graph id starting with /m/ or /g/")
        return v


ExploreLocation = Airport | ExplorePlace | ExploreRegion


def _place_token(place: ExploreLocation) -> list:
    """Serialize a location into the ``[identifier, type]`` wire pair."""
    if isinstance(place, Airport):
        return [place.name.removeprefix("_"), ExplorePlaceType.AIRPORT.value]
    if isinstance(place, ExploreRegion):
        return [place.value, ExplorePlaceType.REGION.value]
    return [place.mid, place.type_code]


class ExploreSearchFilters(BaseModel):
    """Filters for a Google Flights Explore search.

    Explore shares the FlightsFrontendService request message with the other
    endpoints but wraps it differently (see :meth:`format`).

    ``departure_date`` is required — the endpoint returns an opaque error 13
    without one (the UI's "flexible dates" mode uses request slots this
    capture did not exercise).

    ``trip_length_window`` is ``[4, 23, min_nights, max_nights]``: the
    leading ``4, 23`` are constants observed in every capture; the trailing
    pair is the UI's trip-length slider. Live probing confirmed the pair
    changes round-trip fares (e.g. forcing exactly 14 nights re-prices every
    destination). Round-trip mode is experimental: without a window forcing a
    minimum stay, quoted fares match one-way prices.
    """

    trip_type: TripType = TripType.ONE_WAY
    passenger_info: PassengerInfo = Field(default_factory=PassengerInfo)
    origin: Airport | ExplorePlace
    destination: ExploreRegion | ExplorePlace | Airport = ExploreRegion.ANYWHERE
    departure_date: str
    stops: MaxStops = MaxStops.ANY
    seat_type: SeatType = SeatType.ECONOMY
    price_limit: PriceLimit | None = None
    airlines: list[Airline] | None = None
    airlines_exclude: list[Airline] | None = None
    alliances: list[Alliance] | None = None
    alliances_exclude: list[Alliance] | None = None
    max_duration: PositiveInt | None = None
    bags: BagsFilter | None = None
    trip_length_window: list[int] | None = None

    @field_validator("trip_type")
    @classmethod
    def validate_trip_type(cls, v: TripType) -> TripType:
        """Explore only supports one-way and round-trip searches."""
        if v == TripType.MULTI_CITY:
            raise ValueError("Explore does not support multi-city trips")
        return v

    @field_validator("departure_date")
    @classmethod
    def validate_departure_date(cls, v: str) -> str:
        """Ensure the departure date is well-formed and not in the past."""
        parsed = datetime.strptime(v, "%Y-%m-%d").date()
        if parsed < datetime.now().date():
            raise ValueError("Departure date cannot be in the past")
        return v

    @model_validator(mode="after")
    def validate_origin_destination(self) -> "ExploreSearchFilters":
        """Ensure origin and destination are not the same place."""
        if _place_token(self.origin) == _place_token(self.destination):
            raise ValueError("Origin and destination cannot be the same place")
        return self

    def format(self) -> list:
        """Format filters into the Explore API request structure.

        Returns the nested list payload for ``GetExploreDestinations``.
        The outer wrapper and the inner request block (slot [3]) were mapped
        from the HAR capture; the inner block shares its layout with
        ``DateSearchFilters.format()``'s filters record, confirming it is the
        same underlying proto message.
        """

        def airline_token(airline: Airline) -> str:
            return airline.name.removeprefix("_")

        # Airline / alliance include list — same merged-token shape as the
        # other endpoints (segment[4]); HAR-confirmed with ["ONEWORLD"].
        include_tokens: list[str] = []
        if self.airlines:
            include_tokens.extend(
                airline_token(a) for a in sorted(self.airlines, key=lambda x: x.value)
            )
        if self.alliances:
            include_tokens.extend(sorted(a.value for a in self.alliances))
        airlines_filters = include_tokens or None

        # Airline / alliance exclude list — slice[5]; inferred from the shared
        # message layout (not exercised in the capture).
        exclude_tokens: list[str] = []
        if self.airlines_exclude:
            exclude_tokens.extend(
                airline_token(a) for a in sorted(self.airlines_exclude, key=lambda x: x.value)
            )
        if self.alliances_exclude:
            exclude_tokens.extend(sorted(a.value for a in self.alliances_exclude))
        exclude_filters = exclude_tokens or None

        # Explore slice — 8 slots, all HAR-confirmed.
        formatted_slice = [
            [[_place_token(self.origin)]],  # 0: origin [[[mid_or_code, type]]]
            [[_place_token(self.destination)]],  # 1: destination [[[mid, type]]]
            self.trip_length_window,  # 2: trip-length window (semantics unconfirmed)
            self.stops.value,  # 3: stops (0=any, 1=nonstop, ...)
            airlines_filters,  # 4: airline / alliance INCLUDE list
            exclude_filters,  # 5: airline / alliance EXCLUDE list
            self.departure_date,  # 6: departure date YYYY-MM-DD
            [self.max_duration] if self.max_duration else None,  # 7: max duration (mins)
        ]

        # Bags — HAR shows [carry_on, checked] here (idx-337 delta: setting
        # "1 carry-on bag" produced [1, 0]); note this is the REVERSE of the
        # [checked, carry_on] order used by GetCalendarGraph (dates.py).
        bags_filter = [int(self.bags.carry_on), self.bags.checked_bags] if self.bags else None

        # Inner request block — mirrors DateSearchFilters' filters record.
        inner = [
            None,  # 0: no observed effect
            None,  # 1: no observed effect
            self.trip_type.value,  # 2: trip type (HAR: 2=one-way)
            None,  # 3: no observed effect
            [],  # 4: reserved slot, always [] in captures
            self.seat_type.value,  # 5: seat class
            [
                self.passenger_info.adults,
                self.passenger_info.children,
                self.passenger_info.infants_on_lap,
                self.passenger_info.infants_in_seat,
            ],  # 6: passengers (same order as the other endpoints)
            [None, self.price_limit.max_price] if self.price_limit else None,  # 7: max price
            None,  # 8: no observed effect
            None,  # 9: no observed effect
            bags_filter,  # 10: bags [carry_on, checked]
            None,  # 11: no observed effect
            None,  # 12: no observed effect
            [formatted_slice],  # 13: slices (Explore always has exactly one)
            None,  # 14: no observed effect
            None,  # 15: no observed effect
            None,  # 16: no observed effect
            1,  # 17: constant in every captured request
            None,  # 18: no observed effect
            None,  # 19: no observed effect
            None,  # 20: no observed effect
            None,  # 21: no observed effect
            None,  # 22: no observed effect
            None,  # 23: no observed effect
            1,  # 24: constant in every captured request
            1,  # 25: constant in every captured request
        ]

        # Outer wrapper — 12 slots, mirrored from the capture. [10] is the
        # UI's map viewport in px and [11] the request trigger (2=initial
        # load, 3=filter change); both are sent as observed constants.
        return [
            [],  # 0
            None,  # 1
            None,  # 2
            inner,  # 3: the search request
            None,  # 4
            1,  # 5: constant in every captured request
            None,  # 6
            0,  # 7: constant in every captured request
            None,  # 8
            0,  # 9: constant in every captured request
            [447, 712],  # 10: map viewport [width, height] px
            3,  # 11: request trigger
        ]

    def encode(self) -> str:
        """URL encode the formatted filters for the API request."""
        formatted_filters = self.format()
        # First convert the formatted filters to a JSON string
        formatted_json = json.dumps(formatted_filters, separators=(",", ":"))
        # Then wrap it in a list with null
        wrapped_filters = [None, formatted_json]
        # Finally, encode the whole thing
        return urllib.parse.quote(json.dumps(wrapped_filters, separators=(",", ":")))


class ExploreDestination(BaseModel):
    """A single Explore result card: a destination and its cheapest fare.

    Fields are left-joined from the two response payloads (destinations and
    prices) on ``mid``; price-side fields are ``None`` when Google found no
    fare for the destination under the current filters.

    ``arrival_date`` is when the cheapest outbound itinerary lands (one day
    after ``departure_date`` for overnight flights) — live probing confirmed
    it is NOT a round-trip return date (it never moves when the trip-length
    window forces longer stays).
    """

    mid: str
    name: str
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    thumbnail_url: str | None = None
    hero_image_url: str | None = None
    departure_date: str | None = None
    arrival_date: str | None = None
    price: NonNegativeFloat | None = None
    currency: str | None = None
    airline: str | None = None
    airline_name: str | None = None
    stops: NonNegativeInt | None = None
    duration_minutes: PositiveInt | None = None
    layover_minutes: NonNegativeInt | None = None
    destination_airport: str | None = None
    origin_mid: str | None = None
    booking_token: str | None = None

    @property
    def price_unknown(self) -> bool:
        """True when Google returned the destination without a fare."""
        return self.price is None


class ExploreResult(BaseModel):
    """The full result of an Explore search."""

    region_name: str | None = None
    origin_name: str | None = None
    price_slider_min: float | None = None
    price_slider_max: float | None = None
    destinations: list[ExploreDestination] = Field(default_factory=list)
