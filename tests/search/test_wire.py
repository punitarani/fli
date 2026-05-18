"""Tests for the wire-format parser shared by all FlightsFrontendService responses."""

import json

from fli.search._wire import iter_wrb_chunks, parse_first_wrb_payload


def _single_chunk(payload):
    """Build the legacy single-chunk response (no length headers)."""
    inner_json = json.dumps(payload, separators=(",", ":"))
    outer = [["wrb.fr", None, inner_json]]
    return ")]}'\n\n" + json.dumps(outer)


def _multi_chunk(*payloads):
    """Build a multi-chunk response with explicit length prefixes.

    Mirrors Google's actual format: each length header counts both the
    leading newline that follows the header AND the trailing newline that
    separates this chunk from the next (i.e. ``len(outer_json) + 1``).
    """
    parts = [")]}'\n\n"]
    for p in payloads:
        inner_json = json.dumps(p, separators=(",", ":"))
        outer_json = json.dumps([["wrb.fr", None, inner_json]], separators=(",", ":"))
        # The length header counts UTF-8 BYTES (not Python str chars) plus
        # the two surrounding newlines. Encoding the JSON before measuring
        # keeps the test correct when payloads contain non-ASCII characters
        # like accented airport names or Japanese carrier strings.
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
        # The length header counts UTF-8 bytes, not characters — confirm a
        # payload with multi-byte chars round-trips correctly (regression
        # guard for the byte-vs-char-length bug in the test helper).
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
