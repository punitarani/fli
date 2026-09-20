"""Flight search CLI command."""

from typing import Annotated, Any

import typer
from pydantic import ValidationError

from fli.cli.enums import OutputFormat
from fli.cli.errors import json_error_payload, report_cli_error
from fli.cli.utils import (
    build_json_error_response,
    build_json_success_response,
    display_flight_results,
    emit_json,
    normalize_cli_date,
    normalize_cli_time_range,
    serialize_flight_result,
    validate_currency,
)
from fli.core import (
    build_flight_segments,
    classify_error,
    format_validation_error,
    google_flights_url,
    parse_airlines,
    parse_alliances,
    parse_cabin_class,
    parse_emissions,
    parse_max_stops,
    parse_sort_by,
    resolve_airport,
    resolve_airports,
)
from fli.core.parsers import ParseError
from fli.models import (
    BagsFilter,
    FlightSearchFilters,
    LayoverRestrictions,
    PassengerInfo,
    TripType,
)
from fli.search import SearchClientError, SearchFlights
from fli.search.flights import SPARSE_PASSENGER_MIX_WARNING


def _search_flights_core(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    departure_window: str | tuple[int, int] | None = None,
    airlines: list[str] | None = None,
    cabin_class: str = "ECONOMY",
    max_stops: str = "ANY",
    sort_by: str = "CHEAPEST",
    exclude_basic_economy: bool = False,
    layover: list[str] | None = None,
    emissions: str = "ALL",
    checked_bags: int = 0,
    carry_on: bool = False,
    all_results: bool = True,
    output_format: OutputFormat = OutputFormat.TEXT,
    currency: str = "USD",
    language: str | None = None,
    country: str | None = None,
    exclude_airlines: list[str] | None = None,
    alliance: list[str] | None = None,
    exclude_alliance: list[str] | None = None,
    min_layover: int | None = None,
    max_layover: int | None = None,
    passengers: int = 1,
    children: int = 0,
    infants_in_seat: int = 0,
    infants_on_lap: int = 0,
    top_n: int | None = None,
) -> None:
    """Core flight search functionality."""
    query: dict[str, Any] = {
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": departure_date,
        "return_date": return_date,
        "departure_window": None,
        "airlines": None,
        "cabin_class": cabin_class.upper(),
        "max_stops": max_stops.upper(),
        "sort_by": sort_by.upper(),
        "passengers": passengers,
        "children": children,
        "infants_in_seat": infants_in_seat,
        "infants_on_lap": infants_on_lap,
    }

    try:
        departure_date = normalize_cli_date(departure_date)
        return_date = normalize_cli_date(return_date)
        departure_window = normalize_cli_time_range(departure_window)
        query["departure_date"] = departure_date
        query["return_date"] = return_date
        query["departure_window"] = (
            f"{departure_window[0]}-{departure_window[1]}" if departure_window else None
        )

        origin_airports = resolve_airports(origin)
        destination_airports = resolve_airports(destination)
        seat_type = parse_cabin_class(cabin_class)
        stops = parse_max_stops(max_stops)
        parsed_airlines = parse_airlines(airlines)
        parsed_exclude_airlines = parse_airlines(exclude_airlines)
        parsed_alliances = parse_alliances(alliance)
        parsed_exclude_alliances = parse_alliances(exclude_alliance)
        query["airlines"] = (
            [airline.name.lstrip("_") for airline in parsed_airlines] if parsed_airlines else None
        )
        query["exclude_airlines"] = (
            [a.name.lstrip("_") for a in parsed_exclude_airlines]
            if parsed_exclude_airlines
            else None
        )
        query["alliances"] = [a.value for a in parsed_alliances] if parsed_alliances else None
        query["exclude_alliances"] = (
            [a.value for a in parsed_exclude_alliances] if parsed_exclude_alliances else None
        )
        sort = parse_sort_by(sort_by)
        emissions_filter = parse_emissions(emissions)

        # Build time restrictions from tuple
        time_restrictions = None
        if departure_window:
            from fli.models import TimeRestrictions

            time_restrictions = TimeRestrictions(
                earliest_departure=departure_window[0],
                latest_departure=departure_window[1],
            )

        # Create flight segments using shared builder
        segments, trip_type = build_flight_segments(
            origin=origin_airports,
            destination=destination_airports,
            departure_date=departure_date,
            return_date=return_date,
            time_restrictions=time_restrictions,
        )

        # `--top-n` only matters once there is a return leg to expand into —
        # it controls how many outbound candidates get chased into
        # GetShoppingResults calls for the return flight (see
        # SearchFlights.search / _expand_multi_leg). Left at its Typer
        # default of None, it silently resolves to the library default (5)
        # for both trip types. Set explicitly on a one-way search, it can
        # never take effect, so we reject it instead of silently ignoring a
        # flag the caller thought was doing something.
        if trip_type == TripType.ONE_WAY:
            if top_n is not None:
                raise ValueError(
                    "--top-n only applies to round-trip searches (it controls how many "
                    "outbound options are expanded into return flights); remove it for "
                    "a one-way search."
                )
            effective_top_n = 5
        else:
            effective_top_n = top_n if top_n is not None else 5
            query["top_n"] = effective_top_n

        # Shareable Google Flights deep link for this search.
        booking_url = google_flights_url(
            origin_airports[0].name.lstrip("_"),
            destination_airports[0].name.lstrip("_"),
            departure_date,
            return_date,
            currency=currency,
            language=language,
            country=country,
        )

        # Parse layover constraints (airports, min duration, max duration).
        layover_restrictions = None
        layover_airports = [resolve_airport(code) for code in layover] if layover else None
        if layover_airports or min_layover is not None or max_layover is not None:
            layover_restrictions = LayoverRestrictions(
                airports=layover_airports,
                min_duration=min_layover,
                max_duration=max_layover,
            )

        # Build bags filter
        bags_filter = None
        if checked_bags > 0 or carry_on:
            bags_filter = BagsFilter(checked_bags=checked_bags, carry_on=carry_on)

        # Create search filters
        filters = FlightSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(
                adults=passengers,
                children=children,
                infants_in_seat=infants_in_seat,
                infants_on_lap=infants_on_lap,
            ),
            flight_segments=segments,
            stops=stops,
            seat_type=seat_type,
            airlines=parsed_airlines,
            airlines_exclude=parsed_exclude_airlines,
            alliances=parsed_alliances,
            alliances_exclude=parsed_exclude_alliances,
            sort_by=sort,
            exclude_basic_economy=exclude_basic_economy,
            layover_restrictions=layover_restrictions,
            emissions=emissions_filter,
            bags=bags_filter,
            show_all_results=all_results,
        )

        # Perform search; `currency` doubles as Google's `curr=` URL param so
        # results come back priced in the requested currency.
        search_client = SearchFlights()
        results = search_client.search(
            filters,
            top_n=effective_top_n,
            currency=currency,
            language=language,
            country=country,
        )

        if not results:
            # Read the library's own verdict rather than recomputing "empty +
            # children/infants" here: SearchFlights.search already knows
            # whether the empty result traces back to a page Google itself
            # served with zero rows, versus the caller's own airline/price/
            # duration/window filter removing rows Google did inline — that
            # distinction lives in the fetch path, not in these arguments,
            # so it can only be answered correctly once, there.
            sparse_note = (
                SPARSE_PASSENGER_MIX_WARNING if search_client.sparse_passenger_mix else None
            )
            if output_format == OutputFormat.JSON:
                emit_json(
                    build_json_success_response(
                        search_type="flights",
                        trip_type=trip_type,
                        query=query,
                        results_key="flights",
                        results=[],
                        booking_url=booking_url,
                        note=sparse_note,
                    )
                )
                return

            # Text mode prints no copy of the note: SearchFlights.search has
            # already logged the same explanation as a warning, which — like
            # every other library warning — reaches the terminal on stderr.
            # Echoing it here showed the user the same paragraph twice. JSON
            # callers rarely read stderr, which is why the note rides in the
            # payload above instead.
            typer.echo("No flights found.")
            raise typer.Exit(1)

        # Build per-flight booking deep-links (tfs; never raises).
        booking_urls = [
            search_client.build_flight_booking_url(
                result,
                currency=currency,
                language=language,
                country=country,
                seat_type=seat_type,
                passenger_info=filters.passenger_info,
            )
            for result in results
        ]

        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_success_response(
                    search_type="flights",
                    trip_type=trip_type,
                    query=query,
                    results_key="flights",
                    results=[
                        serialize_flight_result(result, default_currency=currency, booking_url=burl)
                        for result, burl in zip(results, booking_urls, strict=False)
                    ],
                    booking_url=booking_url,
                )
            )
            return

        display_flight_results(
            results,
            trip_type=trip_type,
            default_currency=currency,
            booking_url=booking_url,
            booking_urls=booking_urls,
        )

    except ParseError as e:
        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_error_response(
                    search_type="flights",
                    message=str(e),
                    query=query,
                    **classify_error(e).as_fields(),
                )
            )
            raise typer.Exit(1) from e

        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
    except ValidationError as e:
        message = format_validation_error(e)
        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_error_response(
                    search_type="flights",
                    message=message,
                    query=query,
                    **classify_error(e).as_fields(),
                )
            )
            raise typer.Exit(1) from e

        typer.echo(f"Error: {message}")
        raise typer.Exit(1) from e
    except (AttributeError, ValueError) as e:
        # Historically this caught a bare AttributeError from an unknown
        # airport/airline code; fli.core.parsers now converts those to
        # ParseError before they ever reach here (see the except above), so
        # in practice this block only sees: a bare ValueError (e.g. the
        # 93-date search-range cap, or any other library call that raises
        # ValueError directly) -> classify_error's validation_error bucket;
        # or a genuine AttributeError from an unrelated bug elsewhere in the
        # call stack -> classify_error's unexpected_error bucket, since it
        # isn't a recognized search-client or input-validation failure.
        # Previously hardcoded "search_error" for both; now routed through
        # classify_error (#248) so the JSON error_type matches what MCP
        # reports for the same input.
        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_error_response(
                    search_type="flights",
                    message=str(e),
                    query=query,
                    **classify_error(e).as_fields(),
                )
            )
            raise typer.Exit(1) from e

        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
    except SearchClientError as e:
        if output_format == OutputFormat.JSON:
            payload_info = json_error_payload(e, command="flights")
            payload = build_json_error_response(
                search_type="flights",
                message=payload_info.message,
                error_type=payload_info.error_type,
                retryable=payload_info.retryable,
                http_status=payload_info.http_status,
                query=query,
            )
            payload["error"]["log_path"] = str(payload_info.log_path)
            emit_json(payload)
            raise typer.Exit(1) from e
        raise report_cli_error(e, command="flights") from e
    except (typer.Exit, typer.Abort):
        # click.exceptions.Exit/Abort are RuntimeError subclasses, so without
        # this clause the broad except below would catch the deliberate
        # `raise typer.Exit(1)` above (empty results) and report it as a
        # crash: bogus "Unexpected error" text plus a traceback log file for
        # a perfectly normal "no flights matched" outcome.
        raise
    except Exception as e:  # noqa: BLE001 — fall back to clean reporting
        if output_format == OutputFormat.JSON:
            payload_info = json_error_payload(e, command="flights")
            payload = build_json_error_response(
                search_type="flights",
                message=payload_info.message,
                error_type=payload_info.error_type,
                retryable=payload_info.retryable,
                http_status=payload_info.http_status,
                query=query,
            )
            payload["error"]["log_path"] = str(payload_info.log_path)
            emit_json(payload)
            raise typer.Exit(1) from e
        raise report_cli_error(e, command="flights") from e


def flights(
    origin: Annotated[
        str,
        typer.Argument(help="Departure airport code, or a comma-separated list (e.g., JFK,LGA)"),
    ],
    destination: Annotated[
        str,
        typer.Argument(help="Arrival airport code, or a comma-separated list (e.g., LHR,LGW)"),
    ],
    departure_date: Annotated[str, typer.Argument(help="Travel date (YYYY-MM-DD)")],
    return_date: Annotated[
        str | None,
        typer.Option(
            "--return",
            "-r",
            help="Return date (YYYY-MM-DD)",
        ),
    ] = None,
    departure_window: Annotated[
        str | None,
        typer.Option(
            "--time",
            "-t",
            help="Departure time window in 24h format (e.g., 6-20)",
        ),
    ] = None,
    airlines: Annotated[
        list[str] | None,
        typer.Option(
            "--airlines",
            "-a",
            help="Airline IATA codes (e.g., BA,KL or repeated --airlines BA --airlines KL)",
        ),
    ] = None,
    cabin_class: Annotated[
        str,
        typer.Option(
            "--class",
            "-c",
            help="Cabin class (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)",
        ),
    ] = "ECONOMY",
    max_stops: Annotated[
        str,
        typer.Option(
            "--stops",
            "-s",
            help="Maximum stops (ANY, 0 for non-stop, 1 for one stop, 2+ for two stops)",
        ),
    ] = "ANY",
    sort_by: Annotated[
        str,
        typer.Option(
            "--sort",
            "-o",
            help="Sort by: TOP_FLIGHTS, BEST, CHEAPEST, DEPARTURE_TIME,"
            " ARRIVAL_TIME, DURATION, EMISSIONS",
        ),
    ] = "CHEAPEST",
    exclude_basic_economy: Annotated[
        bool,
        typer.Option(
            "--exclude-basic",
            "-e",
            help="Exclude basic economy fares. [currently ignored by the search transport]",
        ),
    ] = False,
    layover: Annotated[
        list[str] | None,
        typer.Option(
            "--layover",
            "-l",
            help="Restrict layover to these airports (e.g., -l ORD -l MDW)",
        ),
    ] = None,
    emissions: Annotated[
        str,
        typer.Option(
            "--emissions",
            help=(
                "Filter by emissions level (ALL, LESS). [currently ignored by the search transport]"
            ),
        ),
    ] = "ALL",
    checked_bags: Annotated[
        int,
        typer.Option(
            "--bags",
            "-b",
            help=(
                "Checked bags included in price (0, 1, or 2). "
                "[currently ignored by the search transport]"
            ),
            min=0,
            max=2,
        ),
    ] = 0,
    carry_on: Annotated[
        bool,
        typer.Option(
            "--carry-on",
            help="Include carry-on bag fee in price. [currently ignored by the search transport]",
        ),
    ] = False,
    all_results: Annotated[
        bool,
        typer.Option(
            "--all/--no-all",
            help="Show all available results (default) or only ~30 curated results",
        ),
    ] = True,
    output_format: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            help="Output format: text or json",
            case_sensitive=False,
        ),
    ] = OutputFormat.TEXT,
    currency: Annotated[
        str,
        typer.Option(
            "--currency",
            callback=validate_currency,
            help="Currency code (USD, EUR, GBP, JPY...). Passed to Google as `curr=`.",
        ),
    ] = "USD",
    language: Annotated[
        str | None,
        typer.Option(
            "--language",
            help="Optional BCP-47 language code (e.g., 'en-GB') passed to Google as `hl=`.",
        ),
    ] = None,
    country: Annotated[
        str | None,
        typer.Option(
            "--country",
            help="Optional ISO 3166-1 alpha-2 country code (e.g., 'GB') passed to Google as `gl=`.",
        ),
    ] = None,
    exclude_airlines: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-airlines",
            "-A",
            help=(
                "Airline IATA codes to EXCLUDE from results (e.g., BA,KL "
                "or repeated --exclude-airlines BA --exclude-airlines KL)."
            ),
        ),
    ] = None,
    alliance: Annotated[
        list[str] | None,
        typer.Option(
            "--alliance",
            help=(
                "Restrict results to one or more airline alliances: "
                "ONEWORLD, SKYTEAM, STAR_ALLIANCE (comma-separated allowed)."
            ),
        ),
    ] = None,
    exclude_alliance: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-alliance",
            help="Alliance names to EXCLUDE (ONEWORLD, SKYTEAM, STAR_ALLIANCE).",
        ),
    ] = None,
    min_layover: Annotated[
        int | None,
        typer.Option(
            "--min-layover",
            help="Minimum layover duration in minutes (multi-stop trips only).",
            min=1,
        ),
    ] = None,
    max_layover: Annotated[
        int | None,
        typer.Option(
            "--max-layover",
            help="Maximum layover duration in minutes (multi-stop trips only).",
            min=1,
        ),
    ] = None,
    passengers: Annotated[
        int,
        typer.Option(
            "--passengers",
            "-p",
            help="Number of adult passengers",
            min=1,
        ),
    ] = 1,
    children: Annotated[
        int,
        typer.Option(
            "--children",
            help="Number of children",
            min=0,
        ),
    ] = 0,
    infants_in_seat: Annotated[
        int,
        typer.Option(
            "--infants-in-seat",
            help="Number of infants in seat",
            min=0,
        ),
    ] = 0,
    infants_on_lap: Annotated[
        int,
        typer.Option(
            "--infants-on-lap",
            help="Number of infants on lap",
            min=0,
        ),
    ] = 0,
    top_n: Annotated[
        int | None,
        typer.Option(
            "--top-n",
            help=(
                "Round-trip only: number of outbound options to expand into return-flight "
                "combinations (default 5, 1-10). Cost is 1 + top_n page fetches. Results "
                "all from one airline? Raise this to see more carriers, or change --sort. "
                "Rejected if set on a one-way search."
            ),
            show_default=False,
        ),
    ] = None,
):
    """Search for flights on a specific date.

    Example:
        fli flights JFK LHR 2026-10-25 --time 6-20 --airlines BA,KL --stops NON_STOP
        fli flights JFK LHR 2026-10-25 --format json
        fli flights JFK,LGA LHR,LGW 2026-10-25
        fli flights JFK LHR 2026-10-25 --exclude-basic
        fli flights JFK LAX 2026-10-25 --bags 1 --carry-on
        fli flights JFK LAX 2026-10-25 --emissions LESS
        fli flights JFK LAX 2026-10-25 --all
        fli flights JFK FRA 2026-10-25 --alliance ONEWORLD
        fli flights JFK LAX 2026-10-25 --exclude-airlines DL
        fli flights BUF ATH 2026-10-25 --min-layover 120
        fli flights JFK LHR 2026-10-25 --passengers 2
        fli flights JFK LHR 2026-10-25 --passengers 2 --children 1 --infants-on-lap 1
        fli flights JFK LHR 2026-10-25 --return 2026-11-01 --top-n 8

    """
    _search_flights_core(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        departure_window=departure_window,
        airlines=airlines,
        cabin_class=cabin_class,
        max_stops=max_stops,
        sort_by=sort_by,
        exclude_basic_economy=exclude_basic_economy,
        layover=layover,
        emissions=emissions,
        checked_bags=checked_bags,
        carry_on=carry_on,
        all_results=all_results,
        output_format=output_format,
        currency=currency,
        language=language,
        country=country,
        exclude_airlines=exclude_airlines,
        alliance=alliance,
        exclude_alliance=exclude_alliance,
        min_layover=min_layover,
        max_layover=max_layover,
        passengers=passengers,
        children=children,
        infants_in_seat=infants_in_seat,
        infants_on_lap=infants_on_lap,
        top_n=top_n,
    )
