"""Tests for the wire-format parser shared by all FlightsFrontendService responses."""

import json

import pytest

from fli.search._wire import iter_wrb_chunks, parse_first_wrb_payload
from fli.search.exceptions import SearchBackendError


def _single_chunk(payload):
    """Build the legacy single-chunk response (no length headers)."""
    inner_json = json.dumps(payload, separators=(",", ":"))
    outer = [["wrb.fr", None, inner_json]]
    return ")]}'\n\n" + json.dumps(outer)


def _multi_chunk(*payloads):
    """Build a multi-chunk response with byte-counted length prefixes.

    Each length header counts the chunk plus its two surrounding newlines,
    measured in UTF-8 bytes. Google measures in characters instead (see
    :func:`_google_framed`); both helpers exist so the reader is pinned as
    working under either convention.
    """
    parts = [")]}'\n\n"]
    for p in payloads:
        inner_json = json.dumps(p, separators=(",", ":"))
        outer_json = json.dumps([["wrb.fr", None, inner_json]], separators=(",", ":"))
        byte_len = len(outer_json.encode("utf-8")) + 2
        parts.append(f"{byte_len}\n{outer_json}\n")
    return "".join(parts)


class TestIterWrbChunks:
    def test_single_chunk_legacy_format(self):
        body = _single_chunk([1, "hello", [2, 3]])
        chunks = list(iter_wrb_chunks(body))
        assert chunks == [[1, "hello", [2, 3]]]

    def test_multi_chunk_format_yields_both(self):
        body = _multi_chunk([1, "alpha"], [2, "beta"])
        chunks = list(iter_wrb_chunks(body))
        assert chunks == [[1, "alpha"], [2, "beta"]]

    def test_returns_nothing_for_empty_body(self):
        assert list(iter_wrb_chunks("")) == []

    def test_skips_non_wrb_rows(self):
        body = ")]}'\n\n" + json.dumps(
            [["di", 44], ["af.httprm", 43, "x", 32], ["wrb.fr", None, json.dumps([1])]]
        )
        assert list(iter_wrb_chunks(body)) == [[1]]

    def test_handles_malformed_inner_json_gracefully(self):
        body = ")]}'\n\n" + json.dumps([["wrb.fr", None, "{not valid"]])
        assert list(iter_wrb_chunks(body)) == []

    def test_non_ascii_chunk_payload(self):
        # Multi-byte payloads round-trip under the byte-counted framing.
        body = _multi_chunk([1, "東京", "café", "résumé"])
        chunks = list(iter_wrb_chunks(body))
        assert chunks == [[1, "東京", "café", "résumé"]]


class TestParseFirstWrbPayload:
    def test_returns_first_chunk_only(self):
        body = _multi_chunk([1, "alpha"], [2, "beta"])
        assert parse_first_wrb_payload(body) == [1, "alpha"]

    def test_returns_none_when_empty(self):
        assert parse_first_wrb_payload("") is None


class TestIterWrbChunksEdgeCases:
    def test_bytes_input_works(self):
        body = _single_chunk([1, "hello"])
        chunks_str = list(iter_wrb_chunks(body))
        chunks_bytes = list(iter_wrb_chunks(body.encode("utf-8")))
        assert chunks_str == chunks_bytes

    def test_prefix_only_body_returns_nothing(self):
        # Body is only the JSONP prefix with no actual chunk data.
        assert list(iter_wrb_chunks(b")]}'\n\n")) == []

    def test_whitespace_only_body_returns_nothing(self):
        assert list(iter_wrb_chunks("   \n\n  ")) == []

    def test_malformed_length_header_truncates_stream(self):
        # A non-numeric length header causes the parser to stop cleanly.
        body = ")]}'\n\nabc\n[not parsed]"
        assert list(iter_wrb_chunks(body)) == []

    def test_outer_is_dict_not_list_is_skipped(self):
        body = ")]}'\n\n" + json.dumps({"key": "value"})
        assert list(iter_wrb_chunks(body)) == []

    def test_wrb_row_with_none_inner_skipped(self):
        body = ")]}'\n\n" + json.dumps([["wrb.fr", None, None]])
        assert list(iter_wrb_chunks(body)) == []

    def test_wrb_row_with_non_string_inner_skipped(self):
        body = ")]}'\n\n" + json.dumps([["wrb.fr", None, [1, 2, 3]]])
        assert list(iter_wrb_chunks(body)) == []

    def test_wrb_row_too_short_skipped(self):
        body = ")]}'\n\n" + json.dumps([["wrb.fr", None]])
        assert list(iter_wrb_chunks(body)) == []

    def test_non_wrb_rows_between_multi_chunks_ignored(self):
        parts = [")]}'\n\n"]
        for payload in [[1, "alpha"], [2, "beta"]]:
            inner_json = json.dumps(payload, separators=(",", ":"))
            # Mix wrb.fr row with a di row in each chunk's outer list.
            outer = [["di", 44], ["wrb.fr", None, inner_json]]
            outer_json = json.dumps(outer, separators=(",", ":"))
            byte_len = len(outer_json.encode("utf-8")) + 2
            parts.append(f"{byte_len}\n{outer_json}\n")
        body = "".join(parts)
        chunks = list(iter_wrb_chunks(body))
        assert chunks == [[1, "alpha"], [2, "beta"]]

    def test_multiple_wrb_chunks_all_yielded_with_mixed_rows(self):
        # Two separate multi-chunks, each with only wrb.fr rows.
        body = _multi_chunk([10], [20], [30])
        chunks = list(iter_wrb_chunks(body))
        assert chunks == [[10], [20], [30]]


class TestParseFirstWrbPayloadEdgeCases:
    def test_returns_none_for_only_non_wrb_rows(self):
        body = ")]}'\n\n" + json.dumps([["di", 44], ["af.httprm", 43, "x"]])
        assert parse_first_wrb_payload(body) is None

    def test_skips_invalid_inner_to_find_second_valid_chunk(self):
        # First wrb.fr row has an invalid inner JSON; second is valid.
        bad_inner = "{not valid"
        good_inner = json.dumps([42])
        outer = [["wrb.fr", None, bad_inner], ["wrb.fr", None, good_inner]]
        body = ")]}'\n\n" + json.dumps(outer)
        assert parse_first_wrb_payload(body) == [42]


def _google_framed(*payloads):
    """Build a multi-chunk response framed the way Google actually frames it.

    Measured on a live August 2026 ``GetShoppingResults`` response whose
    airport names carry accents: the length header counts the chunk *plus
    its two surrounding newlines*, in **characters**. On an ASCII-only
    response that is indistinguishable from a byte count, which is why the
    checked-in fixtures never exercised the difference.
    """
    parts = [")]}'\n\n"]
    for p in payloads:
        inner_json = json.dumps(p, separators=(",", ":"), ensure_ascii=False)
        outer_json = json.dumps(
            [["wrb.fr", None, inner_json]], separators=(",", ":"), ensure_ascii=False
        )
        parts.append(f"{len(outer_json) + 2}\n{outer_json}\n")
    return "".join(parts)


def _error_envelope(code):
    """Build the HTTP 200 error envelope Google returns for a rejected request."""
    outer = [
        ["wrb.fr", None, None, None, None, [code]],
        ["di", 39],
        ["af.httprm", 38, "-1963517503", 5],
    ]
    return ")]}'\n\n" + json.dumps(outer, separators=(",", ":"))


class TestNonAsciiFraming:
    """Chunks must survive non-ASCII payloads (issue: 'No flights found')."""

    def test_accented_single_chunk_is_not_dropped(self):
        payload = [None, None, [[["Aéroport de Paris-Charles de Gaulle", "Düsseldorf"]]]]
        assert parse_first_wrb_payload(_google_framed(payload)) == payload

    def test_accented_chunk_does_not_desync_the_stream(self):
        body = _google_framed([1, "Aéroport de Paris-Charles de Gaulle"], [2, "beta"])
        assert list(iter_wrb_chunks(body)) == [
            [1, "Aéroport de Paris-Charles de Gaulle"],
            [2, "beta"],
        ]

    def test_ascii_chunks_still_parse(self):
        body = _google_framed([1, "Paris Charles de Gaulle Airport"], [2, "beta"])
        assert list(iter_wrb_chunks(body)) == [
            [1, "Paris Charles de Gaulle Airport"],
            [2, "beta"],
        ]

    def test_length_header_is_not_trusted(self):
        # A header that matches neither the byte nor the character length
        # must not affect decoding: chunk boundaries come from the JSON
        # grammar, not from the announced length.
        inner_json = json.dumps([1, "café"], separators=(",", ":"), ensure_ascii=False)
        outer_json = json.dumps(
            [["wrb.fr", None, inner_json]], separators=(",", ":"), ensure_ascii=False
        )
        body = f")]}}'\n\n999999\n{outer_json}\n1\n{outer_json}\n"
        assert list(iter_wrb_chunks(body)) == [[1, "café"], [1, "café"]]


class TestErrorEnvelope:
    """Payload-less wrb.fr rows carry a status code and must not read as 'no results'."""

    def test_internal_error_raises(self):
        with pytest.raises(SearchBackendError) as excinfo:
            parse_first_wrb_payload(_error_envelope(13))
        assert excinfo.value.error_code == 13
        assert "13" in str(excinfo.value)
        assert "INTERNAL" in str(excinfo.value)

    def test_invalid_argument_raises(self):
        with pytest.raises(SearchBackendError) as excinfo:
            list(iter_wrb_chunks(_error_envelope(3)))
        assert excinfo.value.error_code == 3
        assert "INVALID_ARGUMENT" in str(excinfo.value)

    def test_unknown_code_still_raises_with_the_number(self):
        with pytest.raises(SearchBackendError) as excinfo:
            parse_first_wrb_payload(_error_envelope(9999))
        assert excinfo.value.error_code == 9999
        assert "9999" in str(excinfo.value)

    def test_payload_less_row_without_status_is_still_skipped(self):
        # Short rows carry no status code — they stay a silent skip.
        body = ")]}'\n\n" + json.dumps([["wrb.fr", None, None]])
        assert list(iter_wrb_chunks(body)) == []
