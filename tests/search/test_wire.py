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
