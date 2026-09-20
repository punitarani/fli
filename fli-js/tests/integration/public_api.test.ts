/**
 * Public-API smoke test — verifies the top-level fli barrel exports
 * everything users need without reaching into internal paths.
 */

import { describe, expect, test } from "bun:test";
import * as fli from "../../src/index.ts";

describe("Public API surface", () => {
  test("exports core enums", () => {
    expect(fli.Airport.JFK).toBe("JFK");
    expect(fli.Airline.AA).toBe("AA");
    expect(fli.SeatType.ECONOMY).toBe(1);
    expect(fli.MaxStops.NON_STOP).toBe(1);
    expect(fli.TripType.ONE_WAY).toBe(2);
    expect(fli.SortBy.CHEAPEST).toBe(2);
    expect(fli.EmissionsFilter.LESS).toBe(1);
    expect(fli.Alliance.STAR_ALLIANCE).toBe("STAR_ALLIANCE");
    expect(fli.Currency.USD).toBe("USD");
  });

  test("exports filter classes", () => {
    expect(typeof fli.FlightSearchFilters).toBe("function");
    expect(typeof fli.DateSearchFilters).toBe("function");
    expect(typeof fli.FlightSegment).toBe("function");
  });

  test("exports search classes", () => {
    expect(typeof fli.SearchFlights).toBe("function");
    expect(typeof fli.SearchDates).toBe("function");
    expect(typeof fli.Client).toBe("function");
  });

  test("exports search exception classes", () => {
    expect(typeof fli.SearchClientError).toBe("function");
    expect(typeof fli.SearchTimeoutError).toBe("function");
    expect(typeof fli.SearchConnectionError).toBe("function");
    expect(typeof fli.SearchHTTPError).toBe("function");
    expect(typeof fli.SearchParseError).toBe("function");
  });

  test("exports core utilities", () => {
    expect(typeof fli.searchAirports).toBe("function");
    expect(typeof fli.parseAirlines).toBe("function");
    expect(typeof fli.buildFlightSegments).toBe("function");
    expect(typeof fli.extractCurrencyFromPriceToken).toBe("function");
    expect(typeof fli.formatPrice).toBe("function");
  });

  test("exports proto helpers", () => {
    expect(typeof fli.buildBookingToken).toBe("function");
    expect(typeof fli.decodeBookingToken).toBe("function");
    expect(typeof fli.extractBookingTokenFromTfu).toBe("function");
  });

  test("exports wire / urls helpers", () => {
    expect(typeof fli.iterWrbChunks).toBe("function");
    expect(typeof fli.parseFirstWrbPayload).toBe("function");
    expect(typeof fli.withLocaleParams).toBe("function");
  });
});
