/**
 * Typed-error family tests.
 *
 * Mirrors fli/search/exceptions.py: every search failure must be a
 * `SearchClientError` so a caller catching "the search failed" catches
 * all of them, including the parse failures that a blocked or reshaped
 * page produces.
 */

import { describe, expect, test } from "bun:test";
import {
  SearchClientError,
  SearchConnectionError,
  SearchHTTPError,
  SearchParseError,
  SearchRejectedError,
  SearchTimeoutError,
  SearchUnsupportedError,
} from "../../src/search/exceptions.ts";
import { iterWrbChunks, parseFirstWrbPayload } from "../../src/search/wire.ts";

describe("error family", () => {
  test("every search error is a SearchClientError", () => {
    for (const err of [
      new SearchTimeoutError("t"),
      new SearchConnectionError("c"),
      new SearchHTTPError("h", 500),
      new SearchParseError("p"),
      new SearchRejectedError(13),
      new SearchUnsupportedError("u"),
    ]) {
      expect(err).toBeInstanceOf(SearchClientError);
      expect(err).toBeInstanceOf(Error);
      expect(err.name).toBe(err.constructor.name);
    }
  });

  test("SearchRejectedError names the code and the gated header", () => {
    const err = new SearchRejectedError(13);
    expect(err.code).toBe(13);
    expect(err.message).toContain("error 13");
    expect(err.message).toContain("x-goog-batchexecute-bgr");
  });

  test("SearchRejectedError without a code omits the suffix", () => {
    expect(new SearchRejectedError().message).not.toContain("error");
  });
});

describe("wire rejection", () => {
  /** A payload-less `wrb.fr` row with an error code parked in slot 5. */
  function rejectedBody(code: unknown): string {
    return `)]}'\n\n${JSON.stringify([["wrb.fr", null, null, null, null, [code]]])}`;
  }

  test("payload-less row with an error code raises instead of yielding nothing", () => {
    expect(() => [...iterWrbChunks(rejectedBody(13))]).toThrow(SearchRejectedError);
    expect(() => parseFirstWrbPayload(rejectedBody(13))).toThrow(/error 13/);
  });

  test("payload-less row with no error code is still skipped", () => {
    const body = `)]}'\n\n${JSON.stringify([["wrb.fr", null, null]])}`;
    expect(parseFirstWrbPayload(body)).toBeNull();
  });

  test("a non-numeric slot-5 value is not mistaken for a code", () => {
    expect(parseFirstWrbPayload(rejectedBody("13"))).toBeNull();
  });
});
