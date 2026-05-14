"""Tests for the rich optional fields added to FlightLeg / FlightResult."""

from datetime import datetime

import pytest

from fli.models import (
    Airline,
    Airport,
    Amenities,
    FlightLeg,
    FlightResult,
    Layover,
)


def _make_leg(**overrides):
    base = {
        "airline": Airline.DL,
        "flight_number": "100",
        "departure_airport": Airport.JFK,
        "arrival_airport": Airport.LAX,
        "departure_datetime": datetime(2026, 7, 15, 20, 25),
        "arrival_datetime": datetime(2026, 7, 15, 23, 43),
        "duration": 378,
    }
    base.update(overrides)
    return FlightLeg(**base)


class TestAmenities:
    def test_all_none_defaults(self):
        a = Amenities()
        assert a.wifi is None
        assert a.power is None
        assert a.usb_power is None
        assert a.in_seat_video is None
        assert a.on_demand_video is None
        assert a.legroom_rating is None

    def test_tri_state(self):
        a = Amenities(wifi=True, power=False, usb_power=None)
        assert a.wifi is True
        assert a.power is False
        assert a.usb_power is None

    def test_legroom_rating_non_negative(self):
        with pytest.raises(ValueError):
            Amenities(legroom_rating=-1)


class TestLayover:
    def test_basic(self):
        lo = Layover(airport=Airport.CDG, duration=130)
        assert lo.airport == Airport.CDG
        assert lo.duration == 130
        assert lo.overnight is False
        assert lo.change_of_airport is False

    def test_overnight_change(self):
        lo = Layover(
            airport=Airport.JFK,
            duration=480,
            overnight=True,
            change_of_airport=True,
        )
        assert lo.overnight is True
        assert lo.change_of_airport is True

    def test_city_and_airport_name_defaults(self):
        lo = Layover(airport=Airport.JFK, duration=60)
        assert lo.city is None
        assert lo.airport_name is None

    def test_city_and_airport_name_populated(self):
        lo = Layover(
            airport=Airport.JFK,
            duration=60,
            city="New York",
            airport_name="John F. Kennedy International Airport",
        )
        assert lo.city == "New York"
        assert lo.airport_name == "John F. Kennedy International Airport"

    def test_negative_duration_rejected(self):
        with pytest.raises(ValueError):
            Layover(airport=Airport.JFK, duration=-1)


class TestFlightLegRichFields:
    def test_defaults_backwards_compatible(self):
        leg = _make_leg()
        assert leg.departure_airport_name is None
        assert leg.arrival_airport_name is None
        assert leg.operating_airline is None
        assert leg.aircraft is None
        assert leg.legroom is None
        assert leg.amenities is None
        assert leg.overnight is False
        assert leg.co2_emissions_g is None

    def test_populated(self):
        leg = _make_leg(
            departure_airport_name="John F. Kennedy International Airport",
            arrival_airport_name="Los Angeles International Airport",
            operating_airline=Airline.DL,
            aircraft="Boeing 767",
            legroom="31 inches",
            legroom_short="31 in",
            amenities=Amenities(wifi=True),
            overnight=False,
            co2_emissions_g=224716,
        )
        assert leg.aircraft == "Boeing 767"
        assert leg.amenities.wifi is True
        assert leg.co2_emissions_g == 224716


class TestFlightResultRichFields:
    def test_defaults_backwards_compatible(self):
        leg = _make_leg()
        flight = FlightResult(legs=[leg], price=164.0, currency="USD", duration=378, stops=0)
        assert flight.layovers is None
        assert flight.co2_emissions_g is None
        assert flight.co2_emissions_typical_g is None
        assert flight.co2_emissions_delta_pct is None
        assert flight.emissions_tag is None
        assert flight.self_transfer is None
        assert flight.mixed_cabin is None
        assert flight.primary_airline is None
        assert flight.booking_token is None

    def test_populated(self):
        leg = _make_leg()
        flight = FlightResult(
            legs=[leg],
            price=164.0,
            currency="USD",
            duration=378,
            stops=0,
            co2_emissions_g=225000,
            co2_emissions_typical_g=355000,
            co2_emissions_delta_pct=-37,
            emissions_tag="lower",
            self_transfer=False,
            mixed_cabin=False,
            primary_airline=Airline.DL,
            primary_airline_name="Delta",
            booking_token="CAISA1VTRBoDCNR/",
        )
        assert flight.emissions_tag == "lower"
        assert flight.co2_emissions_delta_pct == -37
        assert flight.primary_airline_name == "Delta"
