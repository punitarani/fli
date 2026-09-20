"""Unit tests for fli.search._decoders — direct decoder function coverage.

Tests import private helpers directly to cover branches that integration tests
and snapshot fixtures can't reach (warning-log paths, empty/None inputs,
unusual wire-format shapes).
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytest

from fli.search._decoders import (
    _extract_booking_urls,
    _extract_fare_name,
    _parse_emissions,
    _safe_airline,
    parse_booking_chunk,
)


class TestSafeAirline:
    def test_known_code_returns_enum(self):
        from fli.models import Airline

        result = _safe_airline("DL")
        assert result is Airline.DL

    def test_none_returns_none(self):
        assert _safe_airline(None) is None

    def test_empty_string_returns_none(self):
        assert _safe_airline("") is None

    def test_int_returns_none(self):
        assert _safe_airline(42) is None

    def test_sentinel_multi_returns_none_silently(self, caplog):
        with caplog.at_level(logging.WARNING, logger="fli.search._decoders"):
            result = _safe_airline("multi")
        assert result is None
        assert not caplog.records

    def test_unknown_code_returns_none_and_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="fli.search._decoders"):
            result = _safe_airline("ZZFAKE")
        assert result is None
        assert any("ZZFAKE" in r.message for r in caplog.records)


class TestParseDatetime:
    def test_valid_arrays_produce_datetime(self):
        from fli.search._decoders import _parse_datetime

        dt = _parse_datetime([2026, 7, 15], [20, 25])
        assert dt == datetime(2026, 7, 15, 20, 25)

    def test_all_none_date_raises_value_error(self):
        from fli.search._decoders import _parse_datetime

        with pytest.raises(ValueError):
            _parse_datetime([None, None, None], [0, 0])

    def test_all_none_time_raises_value_error(self):
        from fli.search._decoders import _parse_datetime

        with pytest.raises(ValueError):
            _parse_datetime([2026, 1, 1], [None, None])

    def test_none_time_values_coerced_to_zero(self):
        from fli.search._decoders import _parse_datetime

        # None minute → coerced to 0 by the `x or 0` expression.
        dt = _parse_datetime([2026, 7, 15], [10, None])
        assert dt == datetime(2026, 7, 15, 10, 0)


class TestParseEmissions:
    def _detail_with_emissions(self, emissions_block):
        """Build a minimal detail list with the given emissions block at index 22."""
        detail = [None] * 23
        detail[22] = emissions_block
        return detail

    def test_missing_block_returns_all_none(self):
        result = _parse_emissions([])
        assert result == {"this_g": None, "typical_g": None, "delta_pct": None, "tag": None}

    def test_non_list_block_returns_all_none(self):
        result = _parse_emissions(self._detail_with_emissions("bad"))
        assert result["tag"] is None
        assert result["this_g"] is None

    @pytest.mark.parametrize(
        "tag_int, expected_tag",
        [
            (1, "lower"),
            (2, "typical"),
            (3, "higher"),
            (4, None),
        ],
    )
    def test_tag_int_mapping(self, tag_int, expected_tag):
        block = [None] * 12
        block[11] = tag_int
        result = _parse_emissions(self._detail_with_emissions(block))
        assert result["tag"] == expected_tag

    def test_g_values_extracted(self):
        block = [None] * 12
        block[7] = 150000  # this_g
        block[8] = 180000  # typical_g
        block[3] = -17  # delta_pct
        block[11] = 1
        result = _parse_emissions(self._detail_with_emissions(block))
        assert result["this_g"] == 150000
        assert result["typical_g"] == 180000
        assert result["delta_pct"] == -17


class TestExtractBookingUrls:
    def test_returns_vendor_and_google_urls(self):
        block = ["https://vendor.com/book", None, ["/travel/clk?hl=en"]]
        vendor_url, google_url = _extract_booking_urls(block)
        assert vendor_url == "https://vendor.com/book"
        assert google_url == "/travel/clk?hl=en"

    def test_none_block_returns_none_none(self):
        assert _extract_booking_urls(None) == (None, None)

    def test_non_list_block_returns_none_none(self):
        assert _extract_booking_urls("string") == (None, None)

    def test_missing_google_url_returns_none(self):
        block = ["https://vendor.com"]  # len < 3, no block[2]
        vendor_url, google_url = _extract_booking_urls(block)
        assert vendor_url == "https://vendor.com"
        assert google_url is None

    def test_google_url_without_travel_clk_not_returned(self):
        block = ["https://vendor.com", None, ["https://other.com/book"]]
        _, google_url = _extract_booking_urls(block)
        assert google_url is None

    def test_non_string_first_element_returns_none_vendor(self):
        block = [42, None, ["/travel/clk?x=1"]]
        vendor_url, _ = _extract_booking_urls(block)
        assert vendor_url is None


class TestExtractFareName:
    def test_row21_position_preferred(self):
        row = [None] * 22
        row[21] = [None, None, None, "Basic Economy"]
        assert _extract_fare_name(row) == "Basic Economy"

    def test_falls_back_to_row14_nested(self):
        row = [None] * 22
        row[21] = []  # too short — len <= 3
        row[14] = [[[None, [None, "Main Cabin"]]]]
        assert _extract_fare_name(row) == "Main Cabin"

    def test_returns_none_when_both_absent(self):
        row = [None] * 22
        assert _extract_fare_name(row) is None

    def test_empty_string_in_row21_skipped(self):
        row = [None] * 22
        row[21] = [None, None, None, ""]  # empty string is not a valid fare name
        assert _extract_fare_name(row) is None

    def test_row14_fallback_index_error_returns_none(self):
        row = [None] * 22
        row[21] = []
        row[14] = [[[]]]  # too short to reach row[14][0][0][1][1]
        assert _extract_fare_name(row) is None


class TestParseBookingChunk:
    def _make_booking_row(self, index=0, vendor_code="AA", vendor_name="American", price=100.0):
        """Build a minimal booking row that passes _try_parse_booking_row's shape checks."""
        return [
            index,  # [0] int
            [[vendor_code, vendor_name]],  # [1] vendor list
            None,  # [2]
            [],  # [3] flights
            None,  # [4]
            None,  # [5] URL block
            None,  # [6]
            [[None, price]],  # [7] price block
        ]

    def test_empty_chunk_returns_empty_list(self):
        assert parse_booking_chunk([]) == []

    def test_none_chunk_returns_empty_list(self):
        assert parse_booking_chunk(None) == []

    def test_finds_booking_row_at_top_level(self):
        row = self._make_booking_row(vendor_code="UA", price=250.0)
        result = parse_booking_chunk([row])
        assert len(result) == 1
        assert result[0].vendor_code == "UA"
        assert result[0].price == 250.0

    def test_finds_booking_row_nested_one_level(self):
        row = self._make_booking_row(vendor_code="DL", price=199.0)
        result = parse_booking_chunk([[row]])
        assert len(result) == 1
        assert result[0].vendor_code == "DL"

    def test_non_booking_shape_lists_are_ignored(self):
        # A list with a string first element doesn't match (needs int at [0]).
        result = parse_booking_chunk([["not", "a", "booking", "row", None, None, None, None]])
        assert result == []

    def test_multiple_booking_rows_all_returned(self):
        row1 = self._make_booking_row(index=0, vendor_code="AA", price=300.0)
        row2 = self._make_booking_row(index=1, vendor_code="UA", price=320.0)
        result = parse_booking_chunk([row1, row2])
        assert len(result) == 2
        codes = {r.vendor_code for r in result}
        assert codes == {"AA", "UA"}
