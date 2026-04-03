"""Hotel search CLI command."""

import json
from typing import Annotated, Any

import typer
from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fli.cli.console import console
from fli.cli.enums import OutputFormat
from fli.cli.utils import (
    build_json_error_response,
    emit_json,
    normalize_cli_date,
)
from fli.core import format_price
from fli.core.parsers import ParseError
from fli.search.hotels import HotelResult, SearchHotels


def serialize_hotel_result(hotel: HotelResult) -> dict[str, Any]:
    """Serialize a hotel result for JSON output."""
    return {
        "name": hotel.name,
        "price": hotel.price,
        "rating": hotel.rating,
        "url": hotel.url,
        "amenities": hotel.amenities or [],
    }


def display_hotel_results(hotels: list[HotelResult], location: str, dates: str):
    """Display hotel results in a formatted table."""
    if not hotels:
        console.print(Panel("No hotels found matching your criteria", style="red"))
        return

    table = Table(
        title=f"Hotels in {location} ({dates})",
        box=box.ROUNDED,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Hotel", style="cyan", max_width=40)
    table.add_column("Price/night", style="green", justify="right")
    table.add_column("Rating", style="yellow", justify="center")
    table.add_column("Amenities", style="dim", max_width=40)

    for i, hotel in enumerate(hotels, 1):
        rating_str = f"{hotel.rating:.1f}/5" if hotel.rating else "N/A"
        amenities_str = ", ".join(hotel.amenities[:3]) if hotel.amenities else ""
        if hotel.amenities and len(hotel.amenities) > 3:
            amenities_str += f" +{len(hotel.amenities) - 3} more"

        table.add_row(
            str(i),
            hotel.name,
            format_price(hotel.price),
            rating_str,
            amenities_str,
        )

    console.print(table)
    console.print()


def _search_hotels_core(
    location: str,
    check_in_date: str,
    check_out_date: str,
    adults: int = 2,
    children: int = 0,
    currency: str = "USD",
    sort_by: str | None = None,
    limit: int | None = None,
    output_format: OutputFormat = OutputFormat.TEXT,
) -> None:
    """Core hotel search functionality."""
    query: dict[str, Any] = {
        "location": location,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "adults": adults,
        "children": children,
        "currency": currency.upper(),
        "sort_by": sort_by,
    }

    try:
        check_in_date = normalize_cli_date(check_in_date)
        check_out_date = normalize_cli_date(check_out_date)
        query["check_in_date"] = check_in_date
        query["check_out_date"] = check_out_date

        search_client = SearchHotels()
        results = search_client.search(
            location=location,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            adults=adults,
            children=children,
            currency=currency.upper(),
            sort_by=sort_by,
            limit=limit,
        )

        if not results:
            if output_format == OutputFormat.JSON:
                emit_json(
                    {
                        "success": True,
                        "data_source": "google_travel",
                        "search_type": "hotels",
                        "query": query,
                        "count": 0,
                        "hotels": [],
                    }
                )
                return

            typer.echo("No hotels found.")
            raise typer.Exit(1)

        if output_format == OutputFormat.JSON:
            emit_json(
                {
                    "success": True,
                    "data_source": "google_travel",
                    "search_type": "hotels",
                    "query": query,
                    "count": len(results),
                    "hotels": [serialize_hotel_result(h) for h in results],
                }
            )
            return

        dates_str = f"{check_in_date} to {check_out_date}"
        display_hotel_results(results, location, dates_str)

    except ParseError as e:
        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_error_response(
                    search_type="hotels",
                    message=str(e),
                    query=query,
                )
            )
            raise typer.Exit(1) from e

        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e
    except (AttributeError, ValueError) as e:
        if output_format == OutputFormat.JSON:
            emit_json(
                build_json_error_response(
                    search_type="hotels",
                    message=str(e),
                    error_type="search_error",
                    query=query,
                )
            )
            raise typer.Exit(1) from e

        typer.echo(f"Error: {str(e)}")
        raise typer.Exit(1) from e


def hotels(
    location: Annotated[str, typer.Argument(help="City name or location (e.g., Lima, Tokyo, 'New York')")],
    check_in_date: Annotated[str, typer.Argument(help="Check-in date (YYYY-MM-DD)")],
    check_out_date: Annotated[str, typer.Argument(help="Check-out date (YYYY-MM-DD)")],
    adults: Annotated[
        int,
        typer.Option(
            "--adults",
            "-a",
            help="Number of adult guests",
            min=1,
            max=9,
        ),
    ] = 2,
    children: Annotated[
        int,
        typer.Option(
            "--children",
            "-k",
            help="Number of child guests",
            min=0,
            max=8,
        ),
    ] = 0,
    currency: Annotated[
        str,
        typer.Option(
            "--currency",
            "-c",
            help="Currency code (e.g., USD, EUR, GBP)",
        ),
    ] = "USD",
    sort_by: Annotated[
        str | None,
        typer.Option(
            "--sort",
            "-s",
            help="Sort by: price, rating, or best (value ratio)",
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="Maximum number of results to show",
            min=1,
        ),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            help="Output format: text or json",
            case_sensitive=False,
        ),
    ] = OutputFormat.TEXT,
):
    """Search for hotels at a location.

    Example:
        fli hotels Lima 2026-06-10 2026-06-18
        fli hotels "Buenos Aires" 2026-06-25 2026-07-10 --adults 4 --sort price
        fli hotels Santiago 2026-06-18 2026-06-25 --format json --limit 10

    """
    _search_hotels_core(
        location=location,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        adults=adults,
        children=children,
        currency=currency,
        sort_by=sort_by,
        limit=limit,
        output_format=output_format,
    )
