"""Airport search command for looking up IATA codes."""

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from fli.core.airports import search_airports

console = Console()


def airports(
    query: Annotated[
        str,
        typer.Argument(help="City name, airport name, or IATA code to search for"),
    ],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum results")] = 10,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Search for airports by city name, airport name, or IATA code.

    Example:
        fli airports "new york"
        fli airports tokyo
        fli airports JFK
        fli airports heathrow

    """
    results = search_airports(query, limit=limit)

    if not results:
        console.print(f"[yellow]No airports found matching '{query}'[/yellow]")
        raise typer.Exit(1)

    if json_output:
        import json

        output = [{"code": r.code, "name": r.name, "match_type": r.match_type} for r in results]
        console.print(json.dumps(output, indent=2))
    else:
        table = Table(title=f"Airports matching '{query}'")
        table.add_column("Code", style="bold cyan", width=6)
        table.add_column("Airport Name", style="white")
        table.add_column("Match", style="dim")

        for result in results:
            table.add_row(result.code, result.name, result.match_type)

        console.print(table)
