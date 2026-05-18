"""Tests for SearchFlights._parse_flights_data against synthetic fixtures.

The fixtures here mirror the real Google Flights response structure observed
in `.reverse-eng/notes/response_map.md` (captured live in May 2026). Keeping
them as in-test constants avoids large committed binary blobs while still
locking down the parser positions we depend on.
"""

from fli.models import Airline, Airport
from fli.search.flights import SearchFlights


def _leg(
    *,
    dep_iata,
    arr_iata,
    dep_name="From Airport",
    arr_name="To Airport",
    dep_time=(20, 25),
    arr_time=(23, 43),
    duration=378,
    aircraft="Boeing 767",
    legroom_short="31 in",
    legroom_long="31 inches",
    airline_code="DL",
    flight_number="752",
    operating_code=None,
    airline_name="Delta",
    dep_date=(2026, 7, 15),
    arr_date=(2026, 7, 15),
    co2=224716,
    cabin=2,
    overnight=False,
    amenities=None,
):
    amenities = amenities or [None] * 12
    leg = [None] * 33
    leg[3] = dep_iata
    leg[4] = dep_name
    leg[5] = arr_name
    leg[6] = arr_iata
    leg[8] = list(dep_time)
    leg[10] = list(arr_time)
    leg[11] = duration
    leg[12] = amenities
    leg[14] = legroom_short
    leg[17] = aircraft
    leg[19] = overnight
    leg[20] = list(dep_date)
    leg[21] = list(arr_date)
    leg[22] = [airline_code, flight_number, operating_code, airline_name]
    leg[25] = 1
    leg[30] = legroom_long
    leg[31] = co2
    leg[32] = cabin
    return leg


def _row(
    *,
    legs,
    price=164,
    currency_token=None,
    co2_this=225000,
    co2_typ=355000,
    co2_worst=390000,
    co2_delta_pct=-37,
    co2_tag=1,
    self_transfer=False,
    mixed_cabin=False,
    layovers_block=None,
    primary_airline_code="DL",
    primary_airline_name="Delta",
    booking_token="CAISA1VTRBoDCNR/sample",
):
    detail = [None] * 25
    detail[0] = primary_airline_code
    detail[1] = [primary_airline_name]
    detail[2] = legs
    detail[3] = legs[0][3]
    detail[4] = legs[0][20]
    detail[5] = legs[0][8]
    detail[6] = legs[-1][6]
    detail[7] = legs[-1][21]
    detail[8] = legs[-1][10]
    detail[9] = sum(leg[11] for leg in legs)
    detail[12] = self_transfer
    detail[13] = layovers_block
    emissions = [None] * 18
    emissions[3] = co2_delta_pct
    emissions[7] = co2_this
    emissions[8] = co2_typ
    emissions[10] = co2_worst
    emissions[11] = co2_tag
    detail[22] = emissions

    row = [None] * 11
    row[0] = detail
    row[1] = [[None, price], currency_token]
    row[8] = booking_token
    row[10] = mixed_cabin
    return row


class TestParseFlightsDataNonStop:
    """A baseline non-stop flight parses every rich field correctly."""

    def setup_method(self):
        self.row = _row(
            legs=[
                _leg(
                    dep_iata="JFK",
                    arr_iata="LAX",
                    amenities=[None, True, None, None, None, True, None, None, None, True, None, 2],
                )
            ],
        )
        self.flight = SearchFlights._parse_flights_data(self.row)

    def test_price_and_basics(self):
        assert self.flight.price == 164.0
        assert self.flight.duration == 378
        assert self.flight.stops == 0
        assert len(self.flight.legs) == 1

    def test_leg_airports_and_airline(self):
        leg = self.flight.legs[0]
        assert leg.airline == Airline.DL
        assert leg.flight_number == "752"
        assert leg.departure_airport == Airport.JFK
        assert leg.arrival_airport == Airport.LAX
        assert leg.departure_airport_name == "From Airport"
        assert leg.arrival_airport_name == "To Airport"

    def test_leg_aircraft_legroom(self):
        leg = self.flight.legs[0]
        assert leg.aircraft == "Boeing 767"
        assert leg.legroom == "31 inches"
        assert leg.legroom_short == "31 in"

    def test_leg_co2(self):
        assert self.flight.legs[0].co2_emissions_g == 224716

    def test_leg_amenities_populated(self):
        am = self.flight.legs[0].amenities
        assert am is not None
        assert am.wifi is True
        assert am.power is True
        assert am.on_demand_video is True
        assert am.legroom_rating == 2
        # USB/in-seat-video slots not yet disambiguated — left as None to
        # avoid lying about what we know.
        assert am.usb_power is None
        assert am.in_seat_video is None

    def test_result_emissions(self):
        assert self.flight.co2_emissions_g == 225000
        assert self.flight.co2_emissions_typical_g == 355000
        assert self.flight.co2_emissions_delta_pct == -37
        assert self.flight.emissions_tag == "lower"

    def test_no_layovers_for_nonstop(self):
        assert self.flight.layovers is None

    def test_primary_airline(self):
        assert self.flight.primary_airline == Airline.DL
        assert self.flight.primary_airline_name == "Delta"

    def test_booking_token(self):
        assert self.flight.booking_token == "CAISA1VTRBoDCNR/sample"


class TestParseFlightsDataLayover:
    """A multi-leg trip derives layover info from leg timestamps."""

    def setup_method(self):
        leg1 = _leg(
            dep_iata="JFK",
            arr_iata="CDG",
            dep_time=(19, 15),
            arr_time=(9, 5),
            dep_date=(2026, 7, 15),
            arr_date=(2026, 7, 16),
            duration=470,
            airline_code="DL",
            flight_number="262",
            aircraft="Boeing 767",
        )
        leg2 = _leg(
            dep_iata="CDG",
            arr_iata="ATH",
            dep_time=(13, 20),
            arr_time=(17, 40),
            dep_date=(2026, 7, 16),
            arr_date=(2026, 7, 16),
            duration=200,
            airline_code="AF",
            flight_number="1832",
            aircraft="Airbus A321",
        )
        self.row = _row(
            legs=[leg1, leg2],
            price=618,
            co2_this=625000,
            co2_typ=533000,
            co2_delta_pct=17,
            co2_tag=3,
            primary_airline_code="DL",
            primary_airline_name="Delta",
        )
        self.flight = SearchFlights._parse_flights_data(self.row)

    def test_stops_count(self):
        assert self.flight.stops == 1

    def test_layovers_present(self):
        assert self.flight.layovers is not None
        assert len(self.flight.layovers) == 1

    def test_layover_airport_and_duration(self):
        lo = self.flight.layovers[0]
        assert lo.airport == Airport.CDG
        # 13:20 - 09:05 = 4h15 = 255 minutes
        assert lo.duration == 255

    def test_layover_overnight_flag(self):
        # Arrival 2026-07-16 09:05; departure 2026-07-16 13:20 (same day)
        assert self.flight.layovers[0].overnight is False

    def test_layover_change_of_airport_flag(self):
        # Same airport (CDG -> CDG)
        assert self.flight.layovers[0].change_of_airport is False

    def test_emissions_tag_higher(self):
        assert self.flight.emissions_tag == "higher"
        assert self.flight.co2_emissions_delta_pct == 17


class TestLayoverDetailBlockEnrichment:
    """``_derive_layovers`` merges city / airport_name from ``detail[13]`` when present."""

    def _build_row(self, layovers_block):
        leg1 = _leg(
            dep_iata="JFK",
            arr_iata="CDG",
            dep_date=(2026, 7, 15),
            arr_date=(2026, 7, 16),
            dep_time=(22, 0),
            arr_time=(9, 5),
            duration=395,
            airline_code="DL",
            flight_number="100",
            airline_name="Delta",
        )
        leg2 = _leg(
            dep_iata="CDG",
            arr_iata="FRA",
            dep_date=(2026, 7, 16),
            arr_date=(2026, 7, 16),
            dep_time=(13, 20),
            arr_time=(15, 0),
            duration=100,
            airline_code="AF",
            flight_number="200",
            airline_name="Air France",
        )
        return _row(legs=[leg1, leg2], layovers_block=layovers_block)

    def test_city_and_airport_name_populated(self):
        # Google's detail[13] layover entry:
        # [duration_mins, IATA, IATA, None, airport_name, city, ...]
        row = self._build_row(
            layovers_block=[[255, "CDG", "CDG", None, "Charles de Gaulle Airport", "Paris"]],
        )
        flight = SearchFlights._parse_flights_data(row)
        assert flight.layovers is not None
        lo = flight.layovers[0]
        assert lo.airport_name == "Charles de Gaulle Airport"
        assert lo.city == "Paris"

    def test_missing_entry_yields_none_fields(self):
        """detail[13] absent ⇒ derived layover has both enrichment fields as None."""
        row = self._build_row(layovers_block=None)
        flight = SearchFlights._parse_flights_data(row)
        lo = flight.layovers[0]
        assert lo.airport_name is None
        assert lo.city is None

    def test_malformed_entry_does_not_raise(self):
        """A None or empty entry in detail[13] is tolerated."""
        for bad in ([None], [[]], [["only-one-element"]]):
            row = self._build_row(layovers_block=bad)
            flight = SearchFlights._parse_flights_data(row)
            lo = flight.layovers[0]
            assert lo.airport_name is None
            assert lo.city is None


class TestParseFlightsDataDefensive:
    """Parser handles missing optional fields without raising."""

    def test_missing_emissions_block(self):
        row = _row(legs=[_leg(dep_iata="JFK", arr_iata="LAX")])
        # Wipe the emissions block to simulate older / partial responses.
        row[0][22] = None
        flight = SearchFlights._parse_flights_data(row)
        assert flight.co2_emissions_g is None
        assert flight.emissions_tag is None

    def test_missing_booking_token(self):
        row = _row(legs=[_leg(dep_iata="JFK", arr_iata="LAX")])
        row[8] = None
        flight = SearchFlights._parse_flights_data(row)
        assert flight.booking_token is None

    def test_missing_amenities_slot(self):
        row = _row(legs=[_leg(dep_iata="JFK", arr_iata="LAX", amenities=[])])
        flight = SearchFlights._parse_flights_data(row)
        assert flight.legs[0].amenities is None

    def test_missing_operating_carrier(self):
        # Operating code at airline_info[2] = None is the common case.
        row = _row(legs=[_leg(dep_iata="JFK", arr_iata="LAX")])
        flight = SearchFlights._parse_flights_data(row)
        assert flight.legs[0].operating_airline is None


class TestParseFlightsDataEmptyPriceHead:
    """Issue #165 regression: empty price head ``[[], "<token>"]``.

    Google emits this for some round-trip premium-cabin rows (notably
    multi-pax BUSINESS / FIRST searches) — the row is fully valid; the
    aggregate price is simply not pre-computed. The parser should
    surface the row with ``price=None`` and keep the rest of the fields
    intact, rather than dropping it as malformed.
    """

    SHOPPING_TOKEN = (
        # Real captured token; encodes USD as the currency.
        "CjRIQktCNmV1UjNqNjhBR043X0FCRy0tLS0tLS0tLS12dGpkN0FBQUFBR25JcWZNS2pGTTBBEgZV"
        "QTIyMDkaCgjcWxACGgNVU0Q4HHDcWw=="
    )

    def _empty_head_row(self):
        row = _row(legs=[_leg(dep_iata="JFK", arr_iata="LAX")])
        # Replace the default ``[[None, price], token]`` block with the
        # premium-RT shape Google emits: empty head, token present.
        row[1] = [[], self.SHOPPING_TOKEN]
        return row

    def test_parses_with_none_price(self):
        """Row parses successfully and price is None (not 0.0, not raised)."""
        flight = SearchFlights._parse_flights_data(self._empty_head_row())
        assert flight.price is None

    def test_currency_still_decoded(self):
        """Currency is independent of price head — token decode still runs."""
        flight = SearchFlights._parse_flights_data(self._empty_head_row())
        assert flight.currency == "USD"

    def test_other_fields_intact(self):
        """Routing / duration / booking-token fields unaffected by empty price."""
        flight = SearchFlights._parse_flights_data(self._empty_head_row())
        assert len(flight.legs) == 1
        assert flight.duration > 0
        assert flight.booking_token == "CAISA1VTRBoDCNR/sample"

    def test_malformed_non_empty_head_still_raises(self):
        """Empty head is OK; a non-empty head with garbage still fails."""
        import pytest

        row = _row(legs=[_leg(dep_iata="JFK", arr_iata="LAX")])
        row[1] = [[None, "not-a-number"], None]
        with pytest.raises(ValueError, match="not numeric"):
            SearchFlights._parse_flights_data(row)

    def test_non_list_head_still_raises(self):
        """Head must be a list — non-list shapes are still malformed."""
        import pytest

        row = _row(legs=[_leg(dep_iata="JFK", arr_iata="LAX")])
        row[1] = ["not-a-list", None]
        with pytest.raises(ValueError, match="not a list"):
            SearchFlights._parse_flights_data(row)

    def test_price_unknown_property_true_when_none(self):
        """Convenience property returns True when price is None."""
        flight = SearchFlights._parse_flights_data(self._empty_head_row())
        assert flight.price_unknown is True

    def test_price_unknown_property_false_when_priced(self):
        """Convenience property returns False for normally-priced rows."""
        row = _row(legs=[_leg(dep_iata="JFK", arr_iata="LAX")])
        flight = SearchFlights._parse_flights_data(row)
        assert flight.price_unknown is False
