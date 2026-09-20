"""Tests for the wire-format parser shared by all FlightsFrontendService responses."""

import json
import logging
import time

import pytest

from fli.search._wire import _CHUNK_BOUNDARY, iter_wrb_chunks, parse_first_wrb_payload
from fli.search.exceptions import SearchRejectedError


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

    ``json.dumps`` escapes non-ASCII by default, so the bodies this builds
    are pure ASCII and the two counts coincide in them. The byte count is
    exercised against a genuinely multi-byte body in
    ``TestNonAsciiFraming.test_byte_counted_framing_of_the_same_body_also_parses``.
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


def _google_framed(*payloads: object) -> str:
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


def _error_envelope(code: int) -> str:
    """Build the HTTP 200 error envelope Google returns for a rejected request."""
    outer = [
        ["wrb.fr", None, None, None, None, [code]],
        ["di", 39],
        ["af.httprm", 38, "-1963517503", 5],
    ]
    return ")]}'\n\n" + json.dumps(outer, separators=(",", ":"))


def _error_status_row(status: object) -> list[object]:
    """Build a payload-less ``wrb.fr`` row carrying an arbitrary status field."""
    return ["wrb.fr", None, None, None, None, status]


def _rows_body(*rows: object) -> str:
    """Wrap already-built outer rows into a single-chunk response body."""
    return ")]}'\n\n" + json.dumps(list(rows), separators=(",", ":"))


def _payload_row(payload: object) -> list[object]:
    """Build a normal ``wrb.fr`` row carrying an inner JSON payload."""
    return ["wrb.fr", None, json.dumps(payload, separators=(",", ":"))]


def _malformed_chunks(count: int) -> str:
    """Build a header-framed body whose every chunk fails to decode.

    Each chunk fails at a fixed, tiny offset into itself, so the number of
    decode failures equals ``count`` and the only thing that grows is how
    far into the body each failure happens.
    """
    chunk = "[not json]"
    parts = [")]}'\n\n"]
    parts.extend(f"{len(chunk) + 2}\n{chunk}\n" for _ in range(count))
    return "".join(parts)


def _crlf_framed_chunks(count: int) -> str:
    """Build valid chunks framed with CRLF headers.

    The boundary pattern is newline-based, so a CRLF body carries no
    boundary the reader can find — which is exactly the shape that must
    not degrade into a per-chunk scan to the end of the document.
    """
    parts = [")]}'\r\n\r\n"]
    for index in range(count):
        chunk = json.dumps([_payload_row([index])], separators=(",", ":"))
        parts.append(f"{len(chunk) + 2}\r\n{chunk}\r\n")
    return "".join(parts)


def _back_to_back_chunks(count: int) -> str:
    """Build valid chunks with no length headers and nothing between them."""
    parts = [")]}'\n\n"]
    parts.extend(
        json.dumps([_payload_row([index])], separators=(",", ":")) for index in range(count)
    )
    return "".join(parts)


def _newline_separated_chunks(count: int) -> str:
    """Build valid chunks with no length headers, one newline between them."""
    body = "\n".join(
        json.dumps([_payload_row([index])], separators=(",", ":")) for index in range(count)
    )
    return ")]}'\n\n" + body


def _sized_body(megabytes: float) -> str:
    """Build a valid two-chunk body of roughly ``megabytes`` characters."""
    # ~37 characters per element, so the row count sets the size directly.
    rows = int(megabytes * 1_000_000 / 37)
    return _google_framed(["Aéroport de Paris-Charles de Gaulle"] * rows, [1, "beta"])


def _elapsed_over_body(body: str, repeats: int = 3) -> float:
    """Return the fastest of ``repeats`` full reads of ``body``, in seconds."""
    best = float("inf")
    for _ in range(repeats):
        started = time.perf_counter()
        list(iter_wrb_chunks(body))
        best = min(best, time.perf_counter() - started)
    return best


def _elapsed_quietly(body: str) -> float:
    """Time a full read of ``body`` with this module's logger silenced.

    Logging is a per-bad-chunk cost of its own; silencing it keeps a
    timing measurement about the reader rather than about whatever
    handler happens to be attached to the root logger.
    """
    logger = logging.getLogger("fli.search._wire")
    previous = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        return _elapsed_over_body(body)
    finally:
        logger.setLevel(previous)


def _assert_scales_linearly(shape, sizes: tuple[int, int, int], label: str) -> str:
    """Assert 4x the work costs well under 4x^2 the time, and describe the run.

    Linear is ~4x for 4x the work and quadratic is ~16x, so the bound sits
    between them and nowhere near either — a noisy box cannot cross it.
    """
    small, medium, large = (_elapsed_quietly(shape(size)) for size in sizes)
    ratio = large / max(small, 1e-6)
    timings = f"{small * 1000:.1f} / {medium * 1000:.1f} / {large * 1000:.1f} ms"
    assert ratio < 8, f"{label}: 4x the work took {ratio:.1f}x the time ({timings}) — not linear"
    return f"{label}: {timings} ({ratio:.2f}x)"


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

    def test_byte_counted_framing_of_the_same_body_also_parses(self):
        # The other plausible reading of the header: UTF-8 bytes. ``_multi_chunk``
        # covers the byte count too, but ``json.dumps`` escapes non-ASCII by
        # default, so its bodies are pure ASCII and the two counts coincide
        # there. This builds the raw multi-byte body and announces its byte
        # length, which is what pins the reader as correct under either
        # convention rather than merely under Google's.
        payloads = ([1, "Aéroport de Paris-Charles de Gaulle"], [2, "Düsseldorf"])
        parts = [")]}'\n\n"]
        for payload in payloads:
            inner_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            outer_json = json.dumps(
                [["wrb.fr", None, inner_json]], separators=(",", ":"), ensure_ascii=False
            )
            parts.append(f"{len(outer_json.encode('utf-8')) + 2}\n{outer_json}\n")
        body = "".join(parts)
        # The two conventions really do disagree on this body.
        assert len(body.encode("utf-8")) != len(body)
        assert list(iter_wrb_chunks(body)) == list(payloads)

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


class TestGrammarDelimitingRobustness:
    """The JSON grammar — not the announced length — has to find every edge."""

    def test_payload_strings_may_contain_framing_characters(self):
        # Brackets, quotes and backslashes inside a string must not be
        # mistaken for structure: json.dumps escapes them, and the reader
        # relies on the decoder rather than scanning for "[" itself.
        payload = [
            'a "quoted" [bracket] value',
            'back\\slash and \\" escaped quote',
            "accented é with a ] and a newline\nin the middle",
        ]
        body = _google_framed(payload, [2, "beta"])
        assert list(iter_wrb_chunks(body)) == [payload, [2, "beta"]]

    def test_chunk_survives_a_boundary_that_falls_mid_string(self):
        # The announced length cuts each chunk in half, in the middle of a
        # string that itself contains "[". A length-slicing reader hands
        # json.loads a truncated document and loses the rest of the body.
        payload = [1, "x[" * 40]
        inner_json = json.dumps(payload, separators=(",", ":"))
        outer_json = json.dumps([["wrb.fr", None, inner_json]], separators=(",", ":"))
        half = len(outer_json) // 2
        body = f")]}}'\n\n{half}\n{outer_json}\n{half}\n{outer_json}\n"
        assert list(iter_wrb_chunks(body)) == [payload, payload]

    def test_garbage_between_chunks_is_skipped(self):
        good_1 = json.dumps([_payload_row([1, "alpha"])], separators=(",", ":"))
        good_2 = json.dumps([_payload_row([2, "beta"])], separators=(",", ":"))
        body = (
            f")]}}'\n\n{len(good_1) + 2}\n{good_1}\n"
            "<<not json at all>>\n"
            f"{len(good_2) + 2}\n{good_2}\n"
        )
        assert list(iter_wrb_chunks(body)) == [[1, "alpha"], [2, "beta"]]

    def test_truncated_final_chunk_is_skipped_with_one_concise_warning(self, caplog):
        # A transfer cut short must not hang, and must not raise out of the
        # generator — the chunks that did arrive are still delivered.
        good = json.dumps([_payload_row([1, "alpha"])], separators=(",", ":"))
        truncated = json.dumps([_payload_row([2, "beta"])], separators=(",", ":"))[:-12]
        body = f")]}}'\n\n{len(good) + 2}\n{good}\n{len(truncated) + 2}\n{truncated}"
        with caplog.at_level(logging.WARNING, logger="fli.search._wire"):
            assert list(iter_wrb_chunks(body)) == [[1, "alpha"]]
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1
        assert "malformed wrb.fr chunk" in warnings[0].getMessage()
        # Tracebacks belong at debug level, not in the operator's log.
        assert warnings[0].exc_info is None

    def test_pathologically_nested_chunk_does_not_escape_the_iterator(self, caplog):
        # 20k unclosed brackets exhaust the decoder's recursion budget.
        # ``RecursionError`` is a ``RuntimeError``, not a ``ValueError``, so
        # it used to sail straight out of the generator and past every
        # caller's ``except SearchClientError``.
        nested = "[" * 20_000
        good = json.dumps([_payload_row([1, "alpha"])], separators=(",", ":"))
        body = f")]}}'\n\n{len(nested) + 2}\n{nested}\n{len(good) + 2}\n{good}\n"
        with caplog.at_level(logging.WARNING, logger="fli.search._wire"):
            assert list(iter_wrb_chunks(body)) == [[1, "alpha"]]
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1
        assert warnings[0].exc_info is None

    def test_deeply_nested_inner_payload_does_not_escape_either(self):
        # Same hazard one level down: the inner JSON string is decoded by a
        # separate ``json.loads`` inside the row walk.
        body = _rows_body(["wrb.fr", None, "[" * 20_000], _payload_row([1, "alpha"]))
        assert list(iter_wrb_chunks(body)) == [[1, "alpha"]]

    def test_repeated_malformed_chunks_do_not_flood_the_log(self, caplog):
        # One warning per bad chunk turns a garbage body into thousands of
        # log lines. Warn on the first few, then summarise.
        with caplog.at_level(logging.WARNING, logger="fli.search._wire"):
            assert list(iter_wrb_chunks(_malformed_chunks(500))) == []
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) <= 6, f"{len(warnings)} warning lines for 500 bad chunks"
        assert "500" in warnings[-1].getMessage()

    def test_valid_path_scales_linearly_with_body_size(self):
        # The happy path must stay linear too. Kept to ~2 MB: a ratio over
        # three sizes proves the shape without a multi-hundred-MB peak.
        _assert_scales_linearly(_sized_body, (0.5, 1.0, 2.0), "header-framed valid, MB")


class TestScalesLinearlyOnEveryBodyShape:
    r"""Every framing shape must be O(n) — including the ones with no boundary.

    The reader looks ahead for the next ``\n<digits>\n[`` to bound each
    decode. A body that has no such boundary — CRLF framing, or chunks
    written back to back with no length headers — must not pay for that
    lookahead once per chunk: an unmatched ``re.search`` scans to the end
    of the document, which is O(n) per chunk and O(n^2) overall. Measured
    before the fix at ~4x per doubling on all three no-boundary shapes,
    where a 2 MB CRLF body took ~57 s against 69 ms for the reader that
    never looked ahead at all.
    """

    def test_header_framed_garbage(self):
        # A failed decode must cost O(chunk), not O(offset-into-the-body):
        # ``JSONDecodeError.__init__`` counts the newlines before the error
        # position, so handing it the whole document once per bad chunk is
        # quadratic too. Measured at ~4x per doubling before round 1.
        _assert_scales_linearly(_malformed_chunks, (4_000, 8_000, 16_000), "header-framed garbage")

    def test_crlf_framed_valid_chunks(self):
        _assert_scales_linearly(_crlf_framed_chunks, (2_000, 4_000, 8_000), "CRLF-framed valid")

    def test_back_to_back_header_less_valid_chunks(self):
        _assert_scales_linearly(_back_to_back_chunks, (2_000, 4_000, 8_000), "back-to-back valid")

    def test_newline_separated_header_less_valid_chunks(self):
        _assert_scales_linearly(
            _newline_separated_chunks, (2_000, 4_000, 8_000), "newline-separated valid"
        )

    def test_every_shape_still_decodes_every_chunk(self):
        # Speed is worthless if the shapes stopped parsing. Pin the output
        # of each one alongside its timing.
        want = [[index] for index in range(50)]
        assert list(iter_wrb_chunks(_crlf_framed_chunks(50))) == want
        assert list(iter_wrb_chunks(_back_to_back_chunks(50))) == want
        assert list(iter_wrb_chunks(_newline_separated_chunks(50))) == want
        assert list(iter_wrb_chunks(_malformed_chunks(50))) == []


# JSON fragments that could sit on either side of a boundary-shaped run of
# characters if one could occur inside a chunk. Deliberately includes the
# cases where "]" / "[" / quotes / escapes are content rather than syntax.
_FRAGMENTS_BEFORE = (
    "",
    "[",
    "[1",
    "[1,",
    "[[",
    "[[1",
    '["a"',
    '["a",',
    '["a\\"b"',
    '["\\\\"',
    '["]"',
    '["["',
    '["\\n"',
    "{",
    '{"k"',
    '{"k":',
    '{"k":1',
    '{"k":1,',
    '{"k":[',
    "[true",
    "[true,",
    "[null,",
    "[-1",
    "[1.5",
    "[1e5",
    "[ ",
    "[\t",
    "[[],",
    "[{},",
    "[1,2",
    "[1,2,",
    '[{"a":1}',
    '[{"a":1},',
    "1",
    "12",
    "[0",
    "[0,",
)

_FRAGMENTS_AFTER = (
    "",
    "]",
    "]]",
    "]]]",
    "1]",
    "1,2]",
    '"a"]',
    "]}",
    "1]}",
    ",2]",
    "],",
    "true]",
    "null]",
    "[]]",
    "{}]",
    '"]',
    '\\"]',
    '{"b":2}]',
    "  ]",
    "\n]",
)

_BOUNDARY_SEPARATORS = (("\n", "\n"), ("\r\n", "\n"), ("\n", "\r\n"), ("\r\n", "\r\n"))

_FRAGMENT_WRAPPERS = ("", "[", "[[", '{"k":[')


class TestChunkBoundaryCannotSplitAValue:
    """The load-bearing claim behind bounding each decode to a window.

    ``_CHUNK_BOUNDARY`` is used to decide where the current chunk ends, so
    the window is only safe if that pattern can never occur strictly inside
    a value the decoder would accept. It cannot, by the JSON grammar: a raw
    newline or carriage return is illegal unescaped inside a string, so the
    digits would have to be a number token surrounded by whitespace — and a
    number followed by ``[`` with only whitespace between them is not valid
    JSON in any container (an array needs a comma, an object a comma or a
    colon, and a top-level document ends after its one value).

    Rather than leave that as prose, this enumerates boundary-shaped
    strings wedged between JSON fragments and checks the decoder never
    accepts a value reaching past the boundary.
    """

    def test_boundary_never_lands_inside_an_accepted_value(self):
        decoder = json.JSONDecoder()
        checked = 0
        for wrapper in _FRAGMENT_WRAPPERS:
            for before in _FRAGMENTS_BEFORE:
                for first, second in _BOUNDARY_SEPARATORS:
                    head = wrapper + before + first + "1" + second + "["
                    for after in _FRAGMENTS_AFTER:
                        candidate = head + after
                        checked += 1
                        match = _CHUNK_BOUNDARY.search(candidate)
                        if match is None:
                            continue
                        try:
                            _, end = decoder.raw_decode(candidate, 0)
                        except (ValueError, RecursionError):
                            continue
                        assert end <= match.start(), (
                            f"a boundary at {match.start()} sits inside a value the "
                            f"decoder accepts out to {end}: {candidate!r}"
                        )
        assert checked > 10_000


class TestErrorEnvelope:
    """Payload-less wrb.fr rows carry a status code and must not read as 'no results'."""

    def test_internal_error_raises(self):
        with pytest.raises(SearchRejectedError) as excinfo:
            parse_first_wrb_payload(_error_envelope(13))
        assert excinfo.value.code == 13
        assert "13" in str(excinfo.value)
        assert "INTERNAL" in str(excinfo.value)

    def test_invalid_argument_raises(self):
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(_error_envelope(3)))
        assert excinfo.value.code == 3
        assert "INVALID_ARGUMENT" in str(excinfo.value)

    def test_unknown_code_still_raises_with_the_number(self):
        with pytest.raises(SearchRejectedError) as excinfo:
            parse_first_wrb_payload(_error_envelope(9999))
        assert excinfo.value.code == 9999
        assert "9999" in str(excinfo.value)

    def test_payload_less_row_without_status_is_still_skipped(self):
        # Short rows carry no status code — they stay a silent skip.
        body = ")]}'\n\n" + json.dumps([["wrb.fr", None, None]])
        assert list(iter_wrb_chunks(body)) == []

    def test_ok_status_zero_is_not_an_error(self):
        # 0 is gRPC's OK; it must not surface as "error 0".
        assert list(iter_wrb_chunks(_rows_body(_error_status_row([0])))) == []

    def test_boolean_status_is_not_an_error(self):
        # bool subclasses int — True must not be read as error 1 (CANCELLED).
        assert list(iter_wrb_chunks(_rows_body(_error_status_row([True])))) == []

    def test_negative_status_is_not_an_error(self):
        assert list(iter_wrb_chunks(_rows_body(_error_status_row([-1])))) == []


class TestErrorEnvelopeDetail:
    """The status may carry a message and detail block worth surfacing."""

    def test_detail_block_reaches_the_exception(self):
        # Shape captured live from GetExploreDestinations: the request id and
        # type URL are the debugging hint, not the bare code.
        status = [
            13,
            None,
            [
                [
                    "type.googleapis.com/travel.frontend.flights.ErrorResponse",
                    [[None, None, 0, "req-abc123"], 0],
                ]
            ],
        ]
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(_rows_body(_error_status_row(status))))
        assert excinfo.value.code == 13
        assert "req-abc123" in excinfo.value.detail
        assert "ErrorResponse" in excinfo.value.detail
        assert "req-abc123" in str(excinfo.value)

    def test_status_message_is_surfaced(self):
        status = [7, "missing x-same-domain header"]
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(_rows_body(_error_status_row(status))))
        assert excinfo.value.detail == "missing x-same-domain header"
        assert "missing x-same-domain header" in str(excinfo.value)

    def test_bare_code_has_no_detail(self):
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(_error_envelope(13)))
        assert excinfo.value.detail is None

    def test_oversized_detail_is_truncated(self):
        status = [13, None, [["type.googleapis.com/x", ["y" * 5000]]]]
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(_rows_body(_error_status_row(status))))
        assert len(excinfo.value.detail) == 200
        assert excinfo.value.detail.endswith("…")

    def test_oversized_status_message_is_truncated(self):
        # The message half of the status is Google-controlled text of any
        # length. Uncapped it reached the exception string, the warning
        # record and, through the CLI reporter, a file under ~/.fli/logs.
        status = [13, "M" * 5_000_000]
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(_rows_body(_error_status_row(status))))
        assert len(excinfo.value.detail) <= 200
        assert excinfo.value.detail.endswith("…")
        assert len(str(excinfo.value)) < 1_000

    def test_oversized_message_and_block_together_stay_bounded(self):
        status = [13, "M" * 5_000_000, [["type.googleapis.com/x", ["y" * 5_000_000]]]]
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(_rows_body(_error_status_row(status))))
        assert len(excinfo.value.detail) <= 200
        assert len(str(excinfo.value)) < 1_000

    def test_oversized_message_does_not_reach_the_log_record(self, caplog):
        # Trailing error + a usable chunk is the one path that logs the
        # detail instead of raising it.
        status = [13, "M" * 5_000_000]
        body = _rows_body(_payload_row([1, "alpha"]), _error_status_row(status))
        with caplog.at_level(logging.WARNING, logger="fli.search._wire"):
            assert list(iter_wrb_chunks(body)) == [[1, "alpha"]]
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1
        assert len(warnings[0].getMessage()) < 1_000


class TestSearchRejectedErrorRendering:
    """The exception is built from Google-controlled input; it has to read sanely."""

    def test_zero_is_grpc_ok_so_no_error_number_is_claimed(self):
        # 0 is gRPC's OK. `_wire` never raises it, but a direct caller can,
        # and "declined the request with error 0" is nonsense.
        exc = SearchRejectedError(0)
        assert exc.code == 0
        assert exc.status_name == "OK"
        assert "error 0" not in str(exc)
        assert "declined the request and returned no data" in str(exc)

    def test_no_code_reads_the_same_as_before(self):
        assert "with error" not in str(SearchRejectedError())

    def test_named_code_is_spelled_out(self):
        assert "with error 13 (INTERNAL)" in str(SearchRejectedError(13))

    def test_unknown_code_keeps_the_bare_number(self):
        assert "with error 9999 and" in str(SearchRejectedError(9999))


class TestErrorEnvelopeWithPartialResults:
    """A TRAILING error row must not destroy chunks Google already sent."""

    def test_error_after_a_valid_chunk_keeps_the_chunk(self):
        body = _rows_body(_payload_row([1, "alpha"]), _error_status_row([13]))
        assert list(iter_wrb_chunks(body)) == [[1, "alpha"]]

    def test_error_before_a_valid_chunk_raises(self):
        # Position DOES decide the outcome. An error row that arrives
        # before any usable payload means the request itself was rejected;
        # returning the chunks behind it would hand the caller a partial
        # vendor list under a stderr warning nobody reads.
        body = _rows_body(_error_status_row([13]), _payload_row([1, "alpha"]))
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(body))
        assert excinfo.value.code == 13

    def test_error_before_a_valid_chunk_raises_for_parse_first_too(self):
        body = _rows_body(_error_status_row([13]), _payload_row([1, "alpha"]))
        with pytest.raises(SearchRejectedError):
            parse_first_wrb_payload(body)

    def test_error_in_an_earlier_chunk_of_a_multi_chunk_body_raises(self):
        # Same ruling across chunk boundaries, not just across rows.
        bad = json.dumps([_error_status_row([13])], separators=(",", ":"))
        good = json.dumps([_payload_row([1, "alpha"])], separators=(",", ":"))
        body = f")]}}'\n\n{len(bad) + 2}\n{bad}\n{len(good) + 2}\n{good}\n"
        with pytest.raises(SearchRejectedError):
            list(iter_wrb_chunks(body))

    def test_error_in_a_later_chunk_of_a_multi_chunk_body(self):
        good = json.dumps([_payload_row([1, "alpha"])], separators=(",", ":"))
        bad = json.dumps([_error_status_row([13])], separators=(",", ":"))
        body = f")]}}'\n\n{len(good) + 2}\n{good}\n{len(bad) + 2}\n{bad}\n"
        assert list(iter_wrb_chunks(body)) == [[1, "alpha"]]

    def test_first_payload_is_returned_despite_a_trailing_error(self):
        body = _rows_body(_payload_row([1, "alpha"]), _error_status_row([13]))
        assert parse_first_wrb_payload(body) == [1, "alpha"]

    def test_error_only_body_still_raises_for_both_consumers(self):
        body = _rows_body(_error_status_row([13]))
        with pytest.raises(SearchRejectedError):
            list(iter_wrb_chunks(body))
        with pytest.raises(SearchRejectedError):
            parse_first_wrb_payload(body)

    def test_undecodable_inner_json_does_not_count_as_a_chunk(self):
        # The only payload row is unusable, so the error must still surface.
        body = _rows_body(["wrb.fr", None, "{not valid"], _error_status_row([13]))
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(body))
        assert excinfo.value.code == 13


class TestPayloadLessRowIsRejection:
    """Google's gated RPC answers HTTP 200 with a payload-less row + error 13.

    Yielding nothing there made a hard block indistinguishable from a route
    with no service, which is what left every search reporting "no flights".
    """

    @staticmethod
    def _rejection(code):
        outer = [["wrb.fr", None, None, None, None, [code, "generic::internal: ..."], "generic"]]
        return ")]}'\n\n" + json.dumps(outer)

    def test_error_13_raises_search_rejected(self):
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(self._rejection(13)))
        assert excinfo.value.code == 13
        assert "error 13" in str(excinfo.value)

    def test_rejection_is_exported_from_fli_search(self):
        from fli.search import SearchRejectedError as exported

        assert exported is SearchRejectedError

    def test_parse_first_payload_also_raises(self):
        with pytest.raises(SearchRejectedError):
            parse_first_wrb_payload(self._rejection(13))

    def test_any_numeric_code_is_reported(self):
        with pytest.raises(SearchRejectedError) as excinfo:
            list(iter_wrb_chunks(self._rejection(7)))
        assert excinfo.value.code == 7

    def test_non_numeric_code_is_skipped_not_raised(self):
        """Without a numeric code there is nothing to report — stay silent."""
        outer = [["wrb.fr", None, None, None, None, ["not-a-code"]]]
        body = ")]}'\n\n" + json.dumps(outer)
        assert list(iter_wrb_chunks(body)) == []
