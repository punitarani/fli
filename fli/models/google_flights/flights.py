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
    BagsFilter,
    EmissionsFilter,
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
    sort_by: SortBy = SortBy.BEST
    exclude_basic_economy: bool = False
    emissions: EmissionsFilter = EmissionsFilter.ALL
    bags: BagsFilter | None = None
    show_all_results: bool = True

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

            # Selected flight (to fetch return/next-leg flights)
            selected_flights = None
            is_multi_leg = self.trip_type in (TripType.ROUND_TRIP, TripType.MULTI_CITY)
            if is_multi_leg and segment.selected_flight is not None:
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

            # Emissions filter
            emissions_filter = (
                [self.emissions.value] if self.emissions != EmissionsFilter.ALL else None
            )

            segment_formatted = [
                segment_filters[0],  # departure airport
                segment_filters[1],  # arrival airport
                time_filters,  # time restrictions
                serialize(self.stops.value),  # stops
                airlines_filters,  # airlines
                None,  # unknown: accepts [] but 400s on scalars; seemingly no effect
                segment.travel_date,  # travel date
                [self.max_duration] if self.max_duration else None,  # max duration
                selected_flights,  # selected flight (to fetch return flights)
                layover_airports,  # layover airports
                None,  # unknown: accepts [] but 400s on scalars; seemingly no effect
                None,  # seemingly no effect: accepts any value (0-3, bool) without changing results
                layover_duration,  # layover duration
                emissions_filter,  # emissions filter: [1]=less emissions
                3,  # seemingly no effect: accepts any value (0-5, None) without changing results
            ]
            formatted_segments.append(segment_formatted)

        # Bags filter
        bags_filter = [self.bags.checked_bags, int(self.bags.carry_on)] if self.bags else None

        # The browser uses a wrapper nesting where outer[1] = [[], [main], ...fields...]
        # with self-transfer at wrapper[6] and basic economy at wrapper[15].
        # However, the wrapper format returns empty results through our API client
        # (likely requires browser cookies/headers). We use a flat format instead
        # which the API accepts. NOTE: Self-transfer cannot be toggled in the flat format.
        #
        # Main settings (filters[1]) index map:
        #   0:  unknown - seemingly no effect (tested 0-3, [], "en")
        #   1:  unknown - seemingly no effect (tested "USD"/"EUR"/"GBP"/"JPY");
        #       currency appears to be determined by IP/locale
        #   2:  trip type
        #   3:  unknown - seemingly no effect (tested 0-3)
        #   4:  unknown - seemingly no effect as [] or None; 400s on scalars
        #   5:  seat/cabin type
        #   6:  passenger counts [adults, children, infants_lap, infants_seat]
        #   7:  price limit [None, max_price]
        #   8:  unknown - seemingly no effect (tested 0-3, arrays)
        #   9:  unknown - seemingly no effect (tested 0-3, arrays)
        #   10: bags filter [checked_bags, carry_on]
        #   11: unknown - seemingly no effect (tested 0-3, arrays)
        #   12: unknown - seemingly no effect (tested 0-3, arrays)
        #   13: flight segments
        #   14-16: unknown - seemingly no effect
        #   17: unknown - seemingly no effect (hardcoded to 1)
        #   18-27: unknown - seemingly no effect
        #   28: exclude basic economy (0=allow, 1=exclude)
        #
        filters = [
            [],  # outer[0]
            [
                None,  # [0] seemingly no effect
                None,  # [1] seemingly no effect (not currency)
                serialize(self.trip_type.value),
                None,  # [3] seemingly no effect
                [],  # [4] seemingly no effect
                serialize(self.seat_type.value),
                [
                    self.passenger_info.adults,
                    self.passenger_info.children,
                    self.passenger_info.infants_on_lap,
                    self.passenger_info.infants_in_seat,
                ],
                [None, self.price_limit.max_price] if self.price_limit else None,
                None,  # [8] seemingly no effect
                None,  # [9] seemingly no effect
                bags_filter,  # [10] bags filter [checked_bags, carry_on]
                None,  # [11] seemingly no effect
                None,  # [12] seemingly no effect
                formatted_segments,
                None,  # [14] seemingly no effect
                None,  # [15] seemingly no effect
                None,  # [16] seemingly no effect
                1,  # [17] seemingly no effect (hardcoded to 1)
                None,  # [18] seemingly no effect
                None,  # [19] seemingly no effect
                None,  # [20] seemingly no effect
                None,  # [21] seemingly no effect
                None,  # [22] seemingly no effect
                None,  # [23] seemingly no effect
                None,  # [24] seemingly no effect
                None,  # [25] seemingly no effect
                None,  # [26] seemingly no effect
                None,  # [27] seemingly no effect
                1 if self.exclude_basic_economy else 0,
            ],
            serialize(self.sort_by.value),  # outer[2] sort mode
            1 if self.show_all_results else 0,  # outer[3] 0=~30, 1=all results
            0,  # outer[4] seemingly no effect
            1,  # outer[5] seemingly no effect
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
