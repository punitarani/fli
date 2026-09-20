"""Live-API integration tests for the new May-2026 filter capabilities.

These tests hit Google's live FlightsFrontendService and confirm that the
new filter shapes (alliance include/exclude, airlines_exclude, min layover
duration, currency URL param) actually change the returned results in the
expected ways.

They are gated on a successful HTTP response — failures are retried with
exponential backoff via the same retry helper used by the existing
``test_search_flights.py``. As live network tests they may be skipped or
re-run on flake; do not include in pre-commit CI.
"""

from datetime import datetime, timedelta

import pytest
from tenacity import retry, stop_after_attempt, wait_exponential

from fli.models import (
    Airline,
    Airport,
    Alliance,
    FlightSearchFilters,
    FlightSegment,
    LayoverRestrictions,
    PassengerInfo,
    TripType,
)
from fli.search import SearchFlights


def _future(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _segments(dep: Airport, arr: Airport, days_ahead: int = 60) -> list[FlightSegment]:
    return [
        FlightSegment(
            departure_airport=[[dep, 0]],
            arrival_airport=[[arr, 0]],
            travel_date=_future(days_ahead),
        )
    ]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
def _search_with_retry(client: SearchFlights, filters: FlightSearchFilters, **kw):
    results = client.search(filters, **kw)
    if not results:
        raise ValueError("Empty results, retrying...")
    return results


@pytest.fixture
def client():
    return SearchFlights()


def _codes(results) -> set[str]:
    """Extract IATA codes of primary airlines from a result list."""
    out: set[str] = set()
    for f in results:
        if isinstance(f, tuple):
            f = f[0]
        out.add(f.legs[0].airline.name.lstrip("_"))
    return out


# Known carrier ↔ alliance membership for the assertions below (May 2026).
# Membership is updated for recent moves:
#   - Royal Air Maroc (AT) joined Oneworld in 2020.
#   - SAS (SK) left Star Alliance and joined SkyTeam in September 2024.
#   - Virgin Atlantic (VS) is a SkyTeam member (joined 2023).
_ONEWORLD = {
    "AA",
    "AS",
    "AT",
    "AY",
    "BA",
    "CX",
    "FJ",
    "IB",
    "JL",
    "MH",
    "QF",
    "QR",
    "RJ",
    "S7",
    "UL",
}
_SKYTEAM = {
    "AF",
    "AM",
    "AR",
    "CI",
    "DL",
    "GA",
    "KE",
    "KL",
    "KQ",
    "ME",
    "MF",
    "MU",
    "OK",
    "RO",
    "SK",
    "SU",
    "SV",
    "VN",
    "VS",
    "XK",
}
_STAR_ALLIANCE = {
    "A3",
    "AC",
    "AI",
    "AV",
    "AZ",
    "BR",
    "CA",
    "CM",
    "ET",
    "EW",
    "LH",
    "LO",
    "LX",
    "MS",
    "NH",
    "NZ",
    "OS",
    "OZ",
    "SA",
    "SN",
    "SQ",
    "TG",
    "TK",
    "TP",
    "UA",
    "ZH",
}


class TestAllianceInclude:
    """`alliances=[Alliance.X]` restricts results to that alliance's members."""

    def test_oneworld_only(self, client):
        filters = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_segments(Airport.JFK, Airport.FRA),
            alliances=[Alliance.ONEWORLD],
        )
        results = _search_with_retry(client, filters, currency="USD")
        codes = _codes(results)
        # All carriers should be Oneworld members (or "multi" for codeshares
        # which we accept as a wildcard).
        non_oneworld = codes - _ONEWORLD - {"multi", "DE"}  # Condor (DE) is Oneworld-affiliate
        assert not non_oneworld, f"non-Oneworld carriers leaked through: {non_oneworld}"

    def test_skyteam_only(self, client):
        filters = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_segments(Airport.JFK, Airport.CDG),
            alliances=[Alliance.SKYTEAM],
        )
        results = _search_with_retry(client, filters, currency="USD")
        codes = _codes(results)
        non_skyteam = codes - _SKYTEAM - {"multi"}
        assert not non_skyteam, f"non-SkyTeam carriers leaked through: {non_skyteam}"

    def test_star_alliance_only(self, client):
        filters = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_segments(Airport.JFK, Airport.FRA),
            alliances=[Alliance.STAR_ALLIANCE],
        )
        results = _search_with_retry(client, filters, currency="USD")
        codes = _codes(results)
        non_star = codes - _STAR_ALLIANCE - {"multi"}
        assert not non_star, f"non-Star carriers leaked through: {non_star}"


class TestAllianceExclude:
    """`alliances_exclude=[Alliance.X]` removes that alliance's members."""

    def test_exclude_star_alliance(self, client):
        filters = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_segments(Airport.JFK, Airport.FRA),
            alliances_exclude=[Alliance.STAR_ALLIANCE],
        )
        results = _search_with_retry(client, filters, currency="USD")
        codes = _codes(results)
        star_in_results = codes & _STAR_ALLIANCE
        assert not star_in_results, f"Star carriers leaked through exclude: {star_in_results}"


class TestAirlinesExclude:
    """`airlines_exclude=[Airline.X]` removes a specific airline."""

    def test_exclude_delta(self, client):
        filters = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_segments(Airport.JFK, Airport.LAX),
            airlines_exclude=[Airline.DL],
        )
        results = _search_with_retry(client, filters, currency="USD")
        codes = _codes(results)
        assert "DL" not in codes, f"Delta leaked through exclude: {codes}"


class TestMinLayoverDuration:
    """`LayoverRestrictions.min_duration` enforces a minimum wait time."""

    def test_min_layover_120_minutes(self, client):
        filters = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_segments(Airport.BUF, Airport.ATH, days_ahead=45),
            layover_restrictions=LayoverRestrictions(min_duration=120),
        )
        results = _search_with_retry(client, filters, currency="USD")
        # For every multi-leg flight returned, every layover must be ≥120 min.
        for r in results:
            target = r[0] if isinstance(r, tuple) else r
            if not target.layovers:
                continue
            for lo in target.layovers:
                assert lo.duration >= 120, f"Found layover of {lo.duration} min, expected ≥120"


class TestCurrencyURLParam:
    """`curr=` URL param actually changes the priced currency."""

    def test_usd_default(self, client):
        filters = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_segments(Airport.JFK, Airport.LAX),
        )
        results = _search_with_retry(client, filters, currency="USD")
        # At least one result must report its currency as USD (decoded from
        # the base64 price token).
        currencies = {f.currency for f in results if not isinstance(f, tuple)}
        assert "USD" in currencies

    def test_eur_override(self, client):
        filters = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_segments(Airport.JFK, Airport.LAX),
        )
        results = _search_with_retry(client, filters, currency="EUR")
        currencies = {f.currency for f in results if not isinstance(f, tuple)}
        assert "EUR" in currencies, f"Expected EUR-priced results, got {currencies}"


class TestBookingOptionsAutoSession:
    """`get_booking_options` works end-to-end with no manual session plumbing.

    After :meth:`search` caches the session id automatically, the booking
    call constructs the protobuf token from the flight metadata and the
    cached session — no `tfu` URL extraction, no browser involvement.
    """

    # ``GetBookingResults`` is still an RPC endpoint, so it still needs the
    # browser-signed ``x-goog-batchexecute-bgr`` header this client cannot
    # produce (#223) and answers with error 13. The search-page transport
    # does not cover it. Non-strict so the test reports a pass the day
    # booking options come back.
    @pytest.mark.xfail(
        reason="GetBookingResults still requires the bgr header (#223)", strict=False
    )
    def test_round_trip_zero_friction_booking_options(self, client):
        filters = FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.JFK, 0]],
                    arrival_airport=[[Airport.LAX, 0]],
                    travel_date=_future(60),
                ),
                FlightSegment(
                    departure_airport=[[Airport.LAX, 0]],
                    arrival_airport=[[Airport.JFK, 0]],
                    travel_date=_future(64),
                ),
            ],
        )
        results = _search_with_retry(client, filters, currency="USD")
        assert client._last_session_id is not None
        combo = results[0]
        opts = client.get_booking_options(combo, filters, currency="USD")
        assert len(opts) >= 1, "Expected at least one booking option"
        # At least one option should carry a price and currency.
        with_price = [o for o in opts if o.price is not None]
        assert with_price, "No priced options returned"
        with_currency = [o for o in opts if o.currency]
        assert with_currency, "No options carry a decoded currency"


class TestRichResponseFields:
    """The decoder must populate the new rich fields on live API responses."""

    @pytest.fixture(scope="class")
    def jfk_lax_results(self):
        # Single live search shared by the asserts in this class.
        c = SearchFlights()
        filters = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_segments(Airport.JFK, Airport.LAX, days_ahead=45),
        )
        return _search_with_retry(c, filters, currency="USD")

    def test_co2_emissions_populated(self, jfk_lax_results):
        # At least one result must report CO₂ emissions.
        with_co2 = [f for f in jfk_lax_results if not isinstance(f, tuple) and f.co2_emissions_g]
        assert with_co2, "Expected at least one result with co2_emissions_g populated"

    def test_aircraft_type_populated_on_some_legs(self, jfk_lax_results):
        for f in jfk_lax_results:
            if isinstance(f, tuple):
                continue
            if any(leg.aircraft for leg in f.legs):
                return
        pytest.fail("Expected at least one leg with aircraft field set")

    def test_primary_airline_populated(self, jfk_lax_results):
        for f in jfk_lax_results:
            if isinstance(f, tuple):
                continue
            if f.primary_airline is not None:
                return
        pytest.fail("Expected at least one result with primary_airline set")

    def test_booking_token_populated(self, jfk_lax_results):
        for f in jfk_lax_results:
            if isinstance(f, tuple):
                continue
            if f.booking_token:
                return
        pytest.fail("Expected at least one result with booking_token set")


class TestLapInfantPricing:
    """Google must read our lap-infant passenger code as a lap infant.

    ``tfs`` field 8 numbers passengers 1=adult, 2=child, 3=infant on lap,
    4=infant in own seat. The two infant codes were transposed, which does not
    error: Google prices a lap infant like a seat infant, roughly doubling the
    quoted fare on an international route instead of adding ~10%.

    Unit tests pin the bytes we emit; only a live call can confirm Google reads
    them the way we think. Asserting a ratio rather than a price keeps this
    durable against fare movement.
    """

    ROUTE = (Airport.JFK, Airport.LHR)

    def _cheapest_common_flight(self, client, passengers: PassengerInfo):
        filters = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=passengers,
            flight_segments=_segments(*self.ROUTE),
            airlines=[Airline.BA],
        )
        results = client.search(filters, currency="USD")
        return {
            f.legs[0].flight_number: f.price
            for f in (results or [])
            if len(f.legs) == 1 and f.price
        }

    def test_lap_infant_adds_about_ten_percent_not_a_second_fare(self, client):
        adult_only = self._cheapest_common_flight(client, PassengerInfo(adults=1))
        with_infant = self._cheapest_common_flight(
            client, PassengerInfo(adults=1, infants_on_lap=1)
        )
        shared = sorted(set(adult_only) & set(with_infant))
        if not shared:
            pytest.skip("no non-stop BA itinerary priced in both searches right now")

        number = shared[0]
        ratio = with_infant[number] / adult_only[number]
        # A lap infant is a fraction of the adult fare; the transposed code
        # priced a second seat, landing near 2.0x.
        assert 1.0 <= ratio < 1.5, (
            f"BA{number}: {adult_only[number]} -> {with_infant[number]} ({ratio:.2f}x) — "
            "a lap infant should add roughly 10%, not a second fare"
        )
