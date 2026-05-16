"""Date search CLI command for finding cheapest travel dates."""

from datetime import datetime, timedelta
from typing import Annotated

import typer

from fli.cli.enums import DayOfWeek, OutputFormat
from fli.cli.errors import json_error_payload, report_cli_error
from fli.cli.utils import (
    build_json_error_response,
    build_json_success_response,
    display_date_results,
    emit_json,
    filter_dates_by_days,
    normalize_cli_date,
    normalize_cli_time_range,
    serialize_date_result,
    validate_currency,
)
from fli.core import (
    build_date_search_segments,
    parse_airlines,
    parse_alliances,
    parse_cabin_class,
    parse_max_stops,
    resolve_airport,
)
from fli.core.parsers import ParseError
from fli.models import (
    DateSearchFilters,
    PassengerInfo,
    TimeRestrictions,
    TripType,
)
from fli.search import SearchClientError, SearchDates


def _build_selected_days(
    *,
    monday: bool,
    tuesday: bool,
    wednesday: bool,
    thursday: bool,
    friday: bool,
    saturday: bool,
    sunday: bool,
) -> list[DayOfWeek]:
    """Build the selected day filters list."""
    selected_days = []
    if monday:
        selected_days.append(DayOfWeek.MONDAY)
    if tuesday:
        selected_days.append(DayOfWeek.TUESDAY)
    if wednesday:
        selected_days.append(DayOfWeek.WEDNESDAY)
    if thursday:
        selected_days.append(DayOfWeek.THURSDAY)
    if friday:
        selected_days.append(DayOfWeek.FRIDAY)
    if saturday:
        selected_days.append(DayOfWeek.SATURDAY)
    if sunday:
        selected_days.append(DayOfWeek.SUNDAY)
    return selected_days


def dates(
    origin: Annotated[str, typer.Argument(help="Departure airport IATA code (e.g., JFK)")],
    destination: Annotated[str, typer.Argument(help="Arrival airport IATA code (e.g., LHR)")],
    start_date: Annotated[
        str,
        typer.Option("--from", help="Start date (YYYY-MM-DD)"),
    ] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
    end_date: Annotated[str, typer.Option("--to", help="End date (YYYY-MM-DD)")] = (
        datetime.now() + timedelta(days=60)
    ).strftime("%Y-%m-%d"),
    trip_duration: Annotated[
        int,
        typer.Option(
            "--duration",
            "-d",
            help="Trip duration in days",
        ),
    ] = 3,
    airlines: Annotated[
        list[str] | None,
        typer.Option(
            "--airlines",
            "-a",
            help="Airline IATA codes (e.g., BA,KL or repeated --airlines BA --airlines KL)",
        ),
    ] = None,
    is_round_trip: Annotated[
        bool,
        typer.Option(
            "--round",
            "-R",
            help="Search for round-trip flights",
        ),
    ] = False,
    max_stops: Annotated[
        str,
        typer.Option(
            "--stops",
            "-s",
            help="Maximum stops (ANY, 0 for non-stop, 1 for one stop, 2+ for two stops)",
        ),
    ] = "ANY",
    cabin_class: Annotated[
        str,
        typer.Option(
            "--class",
            "-c",
            help="Cabin class (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)",
        ),
    ] = "ECONOMY",
    sort_by_price: Annotated[
        bool,
        typer.Option(
            "--sort",
            help="Sort results by price (lowest to highest)",
        ),
    ] = False,
    monday: Annotated[
        bool,
        typer.Option(
            "--monday",
            "-mon",
            help="Include Mondays in results",
        ),
    ] = False,
    tuesday: Annotated[
        bool,
        typer.Option(
            "--tuesday",
            "-tue",
            help="Include Tuesdays in results",
        ),
    ] = False,
    wednesday: Annotated[
        bool,
        typer.Option(
            "--wednesday",
            "-wed",
            help="Include Wednesdays in results",
        ),
    ] = False,
    thursday: Annotated[
        bool,
        typer.Option(
            "--thursday",
            "-thu",
            help="Include Thursdays in results",
        ),
    ] = False,
    friday: Annotated[
        bool,
        typer.Option(
            "--friday",
            "-fri",
            help="Include Fridays in results",
        ),
    ] = False,
    saturday: Annotated[
        bool,
        typer.Option(
            "--saturday",
            "-sat",
            help="Include Saturdays in results",
        ),
    ] = False,
    sunday: Annotated[
        bool,
        typer.Option(
            "--sunday",
            "-sun",
            help="Include Sundays in results",
        ),
    ] = False,
    departure_window: Annotated[
        str | None,
        typer.Option(
            "--time",
            "-time",
            help="Departure time window in 24h format (e.g., 6-20)",
        ),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            help="Output format",
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
            help="Airline IATA codes to EXCLUDE from results.",
        ),
    ] = None,
    alliance: Annotated[
        list[str] | None,
        typer.Option(
            "--alliance",
            help="Restrict to alliances: ONEWORLD, SKYTEAM, STAR_ALLIANCE.",
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
):
    """Find the cheapest dates to fly between two airports.

    Example:
        fli dates LAX MIA --class BUSINESS --stops NON_STOP --friday
        fli dates LAX MIA --alliance ONEWORLD --currency EUR
        fli dates LAX MIA --exclude-airlines DL --max-layover 240

    """
    try:
        start_date = normalize_cli_date(start_date)
        end_date = normalize_cli_date(end_date)
        departure_window = normalize_cli_time_range(departure_window)

        # Parse parameters using shared utilities
        origin_airport = resolve_airport(origin)
        destination_airport = resolve_airport(destination)
        trip_type = TripType.ROUND_TRIP if is_round_trip else TripType.ONE_WAY
        stops = parse_max_stops(max_stops)
        seat_type = parse_cabin_class(cabin_class)
        parsed_airlines = parse_airlines(airlines)
        parsed_exclude_airlines = parse_airlines(exclude_airlines)
        parsed_alliances = parse_alliances(alliance)
        parsed_exclude_alliances = parse_alliances(exclude_alliance)
        selected_days = _build_selected_days(
            monday=monday,
            tuesday=tuesday,
            wednesday=wednesday,
            thursday=thursday,
            friday=friday,
            saturday=saturday,
            sunday=sunday,
        )
        query = {
            "origin": origin_airport.name,
            "destination": destination_airport.name,
            "start_date": start_date,
            "end_date": end_date,
            "trip_duration": trip_duration,
            "is_round_trip": is_round_trip,
            "cabin_class": seat_type.name,
            "max_stops": stops.name,
            "departure_window": (
                f"{departure_window[0]}-{departure_window[1]}" if departure_window else None
            ),
            "airlines": (
                [airline.name.lstrip("_") for airline in parsed_airlines]
                if parsed_airlines
                else None
            ),
            "sort_by_price": sort_by_price,
            "days": [day.value for day in selected_days],
        }

        # Build time restrictions from tuple
        time_restrictions = None
        if departure_window:
            start_hour, end_hour = departure_window
            time_restrictions = TimeRestrictions(
                earliest_departure=start_hour,
                latest_departure=end_hour,
                earliest_arrival=None,
                latest_arrival=None,
            )

        # Build flight segments using shared builder
        segments, trip_type = build_date_search_segments(
            origin=origin_airport,
            destination=destination_airport,
            start_date=start_date,
            trip_duration=trip_duration,
            is_round_trip=is_round_trip,
            time_restrictions=time_restrictions,
        )

        # Build layover constraints (min / max duration; airports stay
        # restricted via the existing model field).
        layover_restrictions = None
        if min_layover is not None or max_layover is not None:
            from fli.models import LayoverRestrictions

            layover_restrictions = LayoverRestrictions(
                min_duration=min_layover,
                max_duration=max_layover,
            )

        # Create search filters
        filters = DateSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=segments,
            stops=stops,
            seat_type=seat_type,
            airlines=parsed_airlines,
            airlines_exclude=parsed_exclude_airlines,
            alliances=parsed_alliances,
            alliances_exclude=parsed_exclude_alliances,
            layover_restrictions=layover_restrictions,
            from_date=start_date,
            to_date=end_date,
            duration=trip_duration if trip_type == TripType.ROUND_TRIP else None,
        )

        # Perform search; pass currency/language/country through as URL params.
        search_client = SearchDates()
        results = search_client.search(
            filters,
            currency=currency,
            language=language,
            country=country,
        )

        if not results:
            results = []

        if selected_days:
            results = filter_dates_by_days(results, selected_days, trip_type)

        # Sort dates by price if sort flag is enabled
        if sort_by_price:
            results.sort(key=lambda x: x.price)

        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_success_response(
                    search_type="dates",
                    trip_type=trip_type,
                    query=query,
                    results_key="dates",
                    results=[
                        serialize_date_result(result, trip_type, default_currency=currency)
                        for result in results
                    ],
                )
            )
            return

        if not results:
            message = (
                "No flights found for the selected days."
                if selected_days
                else "No flights found for these dates."
            )
            typer.echo(message)
            raise typer.Exit(1)

        display_date_results(results, trip_type, default_currency=currency)

    except ParseError as e:
        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_error_response(
                    search_type="dates",
                    message=str(e),
                    query={
                        "origin": origin,
                        "destination": destination,
                        "start_date": start_date,
                        "end_date": end_date,
                        "trip_duration": trip_duration,
                        "is_round_trip": is_round_trip,
                        "cabin_class": cabin_class,
                        "max_stops": max_stops,
                        "departure_window": (
                            f"{departure_window[0]}-{departure_window[1]}"
                            if isinstance(departure_window, tuple)
                            else departure_window
                        ),
                        "airlines": airlines,
                        "sort_by_price": sort_by_price,
                        "days": [
                            day.value
                            for day in _build_selected_days(
                                monday=monday,
                                tuesday=tuesday,
                                wednesday=wednesday,
                                thursday=thursday,
                                friday=friday,
                                saturday=saturday,
                                sunday=sunday,
                            )
                        ],
                    },
                )
            )
            raise typer.Exit(1) from e
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
    except SearchClientError as e:
        if output_format == OutputFormat.JSON:
            message, error_type, log_path = json_error_payload(e, command="dates")
            payload = build_json_error_response(
                search_type="dates",
                message=message,
                error_type=error_type,
            )
            payload["error"]["log_path"] = str(log_path)
            emit_json(payload)
            raise typer.Exit(1) from e
        raise report_cli_error(e, command="dates") from e
    except (AttributeError, ValueError) as e:
        if "module 'fli.search' has no attribute 'SearchDates'" in str(e):
            raise
        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_error_response(
                    search_type="dates",
                    message=str(e),
                    error_type="search_error",
                    query={
                        "origin": origin,
                        "destination": destination,
                        "start_date": start_date,
                        "end_date": end_date,
                        "trip_duration": trip_duration,
                        "is_round_trip": is_round_trip,
                        "cabin_class": cabin_class,
                        "max_stops": max_stops,
                        "departure_window": (
                            f"{departure_window[0]}-{departure_window[1]}"
                            if isinstance(departure_window, tuple)
                            else departure_window
                        ),
                        "airlines": airlines,
                        "sort_by_price": sort_by_price,
                        "days": [
                            day.value
                            for day in _build_selected_days(
                                monday=monday,
                                tuesday=tuesday,
                                wednesday=wednesday,
                                thursday=thursday,
                                friday=friday,
                                saturday=saturday,
                                sunday=sunday,
                            )
                        ],
                    },
                )
            )
            raise typer.Exit(1) from e
        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
    except Exception as e:  # noqa: BLE001 — fall back to clean reporting
        if output_format == OutputFormat.JSON:
            message, error_type, log_path = json_error_payload(e, command="dates")
            payload = build_json_error_response(
                search_type="dates",
                message=message,
                error_type=error_type,
            )
            payload["error"]["log_path"] = str(log_path)
            emit_json(payload)
            raise typer.Exit(1) from e
        raise report_cli_error(e, command="dates") from e
