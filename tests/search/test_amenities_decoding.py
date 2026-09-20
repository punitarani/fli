"""Fixture-backed tests for per-leg amenity decoding (issue #217).

Every expectation below is pinned to a *named* flight in a captured
Google Flights response under ``tests/search/fixtures/``, so the slot
mapping is asserted against real wire data rather than a synthetic
guess. The mapping itself was verified by tabulating ``leg[12][0..11]``,
``leg[13]``, ``leg[14]`` and ``leg[16]`` across ~280 distinct legs in
those fixtures and cross-checking against published fleet facts:

- slots 1..6 are a mutually-exclusive *power* group (no leg in the corpus
  has two of them set). Slot 1 is seen on US majors (AC outlet + USB),
  slot 5 on European short-haul and ULCCs (USB only), slot 3 on legacy
  AC-only cabins (AA A319, UA 737).
- slots 8..10 are a mutually-exclusive *video* group. Slot 8 is seen only
  on JetBlue and Delta domestic narrowbodies (live TV), slot 9 on
  widebodies and AA's transcon A321neo (on-demand), slot 10 on fleets
  with no seatback screens at all (Alaska, AA 737/A321 Sharklets,
  regional jets) — i.e. stream-to-your-device.
- slot 11 is a Wi-Fi *tier* code, never a bool: 2 on carriers with free
  Wi-Fi (JetBlue, Delta), 3 on carriers that charge (BA, AF, LH, Alaska).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fli.models import SeatType
from fli.search._decoders import parse_flight_row

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _replay(name: str) -> list:
    body = (FIXTURE_DIR / name).read_text()
    outer = json.loads(body.lstrip(")]}'"))
    inner = json.loads(outer[0][2])
    rows = [item for i in (2, 3) if isinstance(inner[i], list) for item in inner[i][0]]
    flights = []
    for row in rows:
        try:
            flights.append(parse_flight_row(row))
        except (AttributeError, KeyError, ValueError, TypeError):
            continue
    return flights


def _leg(flights: list, carrier: str, number: str):
    for flight in flights:
        for leg in flight.legs:
            if leg.airline.name == carrier and leg.flight_number == number:
                return leg
    raise AssertionError(f"{carrier}{number} not found in fixture")


@pytest.fixture(scope="module")
def jfk_lax():
    return _replay("flight_search_jfk_lax_oneway_usd.bin")


@pytest.fixture(scope="module")
def jfk_fra():
    return _replay("flight_search_jfk_fra_oneworld.bin")


@pytest.fixture(scope="module")
def buf_ath():
    return _replay("flight_search_buf_ath_min_layover_120.bin")


@pytest.fixture(scope="module")
def jfk_lax_no_dl():
    return _replay("flight_search_jfk_lax_exclude_dl.bin")


@pytest.fixture(scope="module")
def lax_lhr_biz():
    return _replay("flight_search_lax_lhr_rt_biz_2a1c.bin")


class TestWifiTier:
    """``leg[12][11]`` is the Wi-Fi tier — slot 1 is power, not Wi-Fi."""

    def test_jetblue_reports_free_wifi(self, jfk_lax):
        # B6 123 (A320): slot 11 == 2. JetBlue is free Wi-Fi fleet-wide.
        leg = _leg(jfk_lax, "B6", "123")
        assert leg.amenities.wifi is True
        assert leg.amenities.wifi_tier == "free"

    def test_delta_transcon_reports_free_wifi(self, jfk_lax):
        leg = _leg(jfk_lax, "DL", "707")
        assert leg.amenities.wifi is True
        assert leg.amenities.wifi_tier == "free"

    def test_american_widebody_reports_paid_wifi(self, jfk_lax):
        # AA 255 (777) carries slot 11 == 3 while AA's narrowbodies carry 2.
        leg = _leg(jfk_lax, "AA", "255")
        assert leg.amenities.wifi is True
        assert leg.amenities.wifi_tier == "paid"

    def test_british_airways_reports_paid_wifi(self, jfk_fra):
        leg = _leg(jfk_fra, "BA", "178")
        assert leg.amenities.wifi is True
        assert leg.amenities.wifi_tier == "paid"

    def test_wifi_unknown_when_tier_slot_absent(self, jfk_fra):
        # BA 904 (A319) stops at slot 5 — no Wi-Fi tier published.
        leg = _leg(jfk_fra, "BA", "904")
        assert leg.amenities.wifi is None
        assert leg.amenities.wifi_tier is None

    def test_wifi_not_read_from_the_power_slot(self, jfk_fra):
        # BA 902 has no power slot 1 but does publish a Wi-Fi tier; the old
        # decoder read slot 1 and reported wifi=None here.
        leg = _leg(jfk_fra, "BA", "902")
        assert leg.amenities.power_type == "usb"
        assert leg.amenities.wifi is True


class TestPowerSlots:
    """Slots 1..6 form the power group; first truthy slot wins."""

    def test_us_major_reports_plug_and_usb(self, jfk_lax):
        leg = _leg(jfk_lax, "AA", "300")
        assert leg.amenities.power is True
        assert leg.amenities.power_type == "plug_and_usb"
        assert leg.amenities.usb_power is True

    def test_jetblue_reports_plug_and_usb(self, jfk_lax):
        leg = _leg(jfk_lax, "B6", "123")
        assert leg.amenities.power is True
        assert leg.amenities.power_type == "plug_and_usb"
        assert leg.amenities.usb_power is True

    def test_european_shorthaul_reports_usb_only(self, jfk_fra):
        # BA 904 (A319) — USB-A charging, no AC outlet.
        leg = _leg(jfk_fra, "BA", "904")
        assert leg.amenities.power is True
        assert leg.amenities.power_type == "usb"
        assert leg.amenities.usb_power is True

    def test_legacy_ac_only_cabin_reports_plug_without_usb(self, buf_ath):
        # AA 1195 (A319) is the only slot-3 shape in the corpus: AC outlet,
        # no USB port.
        leg = _leg(buf_ath, "AA", "1195")
        assert leg.amenities.power is True
        assert leg.amenities.power_type == "plug"
        assert leg.amenities.usb_power is False

    def test_power_unknown_when_no_power_slot_set(self, jfk_fra):
        # IB 1327 (CRJ1000) publishes only the video slot.
        leg = _leg(jfk_fra, "IB", "1327")
        assert leg.amenities.power is None
        assert leg.amenities.power_type is None
        assert leg.amenities.usb_power is None


class TestVideoSlots:
    """Slots 8..10 form the video group; first truthy slot wins."""

    def test_jetblue_reports_live_tv(self, jfk_lax):
        leg = _leg(jfk_lax, "B6", "123")
        assert leg.amenities.video_type == "live_tv"
        assert leg.amenities.in_seat_video is True
        assert leg.amenities.on_demand_video is False

    def test_widebody_reports_on_demand(self, jfk_lax):
        leg = _leg(jfk_lax, "AA", "255")
        assert leg.amenities.video_type == "on_demand"
        assert leg.amenities.in_seat_video is True
        assert leg.amenities.on_demand_video is True

    def test_no_seatback_fleet_reports_stream_to_device(self, jfk_lax):
        # AA 117 flies the A321 (Sharklets) — streaming only, no screens,
        # unlike the A321neo transcon aircraft on AA 300.
        leg = _leg(jfk_lax, "AA", "117")
        assert leg.amenities.video_type == "stream_to_device"
        assert leg.amenities.in_seat_video is False
        assert leg.amenities.on_demand_video is False

    def test_video_unknown_when_no_video_slot_set(self, jfk_fra):
        leg = _leg(jfk_fra, "BA", "904")
        assert leg.amenities.video_type is None
        assert leg.amenities.in_seat_video is None
        assert leg.amenities.on_demand_video is None


class TestSeatQualityAndLegroom:
    """``leg[13]`` labels the seat; ``leg[14]`` carries pitch in inches."""

    def test_above_average_economy_seat(self, jfk_lax):
        leg = _leg(jfk_lax, "B6", "123")
        assert leg.amenities.legroom_rating == 3
        assert leg.amenities.seat_quality == "above_average"
        assert leg.amenities.legroom_inches == 33

    def test_average_economy_seat(self, jfk_lax):
        leg = _leg(jfk_lax, "AA", "300")
        assert leg.amenities.legroom_rating == 1
        assert leg.amenities.seat_quality == "average"
        assert leg.amenities.legroom_inches == 31

    def test_below_average_economy_seat(self, jfk_fra):
        leg = _leg(jfk_fra, "BA", "904")
        assert leg.amenities.legroom_rating == 2
        assert leg.amenities.seat_quality == "below_average"
        assert leg.amenities.legroom_inches == 29

    def test_lie_flat_business_seat(self, lax_lhr_biz):
        # EI 68 (A330) is the long-haul business leg; Google publishes no
        # pitch in inches for lie-flat seats.
        leg = _leg(lax_lhr_biz, "EI", "68")
        assert leg.amenities.legroom_rating == 5
        assert leg.amenities.seat_quality == "lie_flat"
        assert leg.amenities.legroom_inches is None

    def test_domestic_first_recliner(self, jfk_lax_no_dl):
        # AA 1154 (DFW-LAX) appears only as a first-class row in this
        # fixture: a domestic recliner, with no pitch published.
        leg = _leg(jfk_lax_no_dl, "AA", "1154")
        assert leg.amenities.legroom_rating == 8
        assert leg.amenities.seat_quality == "recliner"
        assert leg.amenities.legroom_inches is None

    def test_flagship_business_lie_flat(self, jfk_lax_no_dl):
        # AA 177 is the JFK transcon A321T with a true lie-flat cabin.
        leg = _leg(jfk_lax_no_dl, "AA", "177")
        assert leg.amenities.seat_quality == "lie_flat"


class TestCabin:
    """``leg[16]`` is the per-leg cabin, matching ``SeatType``."""

    def test_economy_leg(self, jfk_lax):
        assert _leg(jfk_lax, "B6", "123").cabin is SeatType.ECONOMY

    def test_business_leg(self, lax_lhr_biz):
        assert _leg(lax_lhr_biz, "EI", "68").cabin is SeatType.BUSINESS

    def test_premium_economy_leg(self, lax_lhr_biz):
        assert _leg(lax_lhr_biz, "EI", "172").cabin is SeatType.PREMIUM_ECONOMY

    def test_first_leg(self, jfk_lax_no_dl):
        assert _leg(jfk_lax_no_dl, "AA", "1154").cabin is SeatType.FIRST

    def test_cabin_is_per_leg_not_per_itinerary(self, lax_lhr_biz):
        # The DUB->LHR partner leg of a business itinerary is plain economy.
        assert _leg(lax_lhr_biz, "BA", "833").cabin is SeatType.ECONOMY

    def test_cabin_tracks_the_fare_not_the_aircraft(self, jfk_lax_no_dl):
        """The same physical flight appears once per bookable cabin.

        AA 1209 (ORD-LAX, 737 MAX 8) shows up twice in this fixture: an
        economy row and a first row. The cabin code and the seat-quality
        code move together, which is what proves ``leg[16]`` describes the
        fare's cabin rather than the airframe.
        """
        cabins = {
            (leg.cabin, leg.amenities.seat_quality)
            for flight in jfk_lax_no_dl
            for leg in flight.legs
            if leg.airline.name == "AA" and leg.flight_number == "1209"
        }
        assert cabins == {
            (SeatType.ECONOMY, "average"),
            (SeatType.FIRST, "recliner"),
        }


class TestCorpusInvariants:
    """Structural properties the decoder relies on, asserted on real data."""

    @staticmethod
    def _raw_legs(name: str):
        body = (FIXTURE_DIR / name).read_text()
        inner = json.loads(json.loads(body.lstrip(")]}'"))[0][2])
        rows = [item for i in (2, 3) if isinstance(inner[i], list) for item in inner[i][0]]
        for row in rows:
            yield from row[0][2] or []

    _FIXTURES = (
        "flight_search_jfk_lax_oneway_usd.bin",
        "flight_search_jfk_lax_eur.bin",
        "flight_search_jfk_lax_exclude_dl.bin",
        "flight_search_jfk_fra_oneworld.bin",
        "flight_search_buf_ath_min_layover_120.bin",
        "flight_search_lax_lhr_rt_biz_2a1c.bin",
    )

    @pytest.mark.parametrize("group", [range(1, 7), range(8, 11)])
    def test_slot_groups_are_mutually_exclusive(self, group):
        for name in self._FIXTURES:
            for fl in self._raw_legs(name):
                slots = fl[12]
                if not isinstance(slots, list):
                    continue
                on = [i for i in group if i < len(slots) and slots[i]]
                assert len(on) <= 1, f"{name}: leg has multiple slots set in {group}: {on}"

    def test_wifi_slot_is_never_a_bool(self):
        """Slot 11 carries a tier code, so it must not be read as a flag."""
        for name in self._FIXTURES:
            for fl in self._raw_legs(name):
                slots = fl[12]
                if isinstance(slots, list) and len(slots) > 11 and slots[11] is not None:
                    assert isinstance(slots[11], int) and not isinstance(slots[11], bool)
