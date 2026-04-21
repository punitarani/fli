#!/usr/bin/env python3
"""CLI entry point for the fli flight search tool."""

import re
import sys

import typer

from fli.cli.commands.dates import dates
from fli.cli.commands.flights import flights
from fli.cli.commands.hotels import hotel_price, hotels

app = typer.Typer(
    help=(
        "Search Google Flights and Google Hotels from the terminal.\n\n"
        "Commands:\n"
        "  flights       Search flights for a specific date\n"
        "  dates         Find cheapest travel dates in a range\n"
        "  hotels        List hotels at a location\n"
        "  hotel-price   Look up price for a specific hotel\n\n"
        "If the first argument looks like a flight search (e.g. 'LAX JFK 2026-07-01'), "
        "it runs the `flights` command by default."
    ),
    add_completion=True,
)

_KNOWN_COMMANDS = {"flights", "dates", "hotels", "hotel-price"}
_HELP_FLAGS = {"--help", "-h"}

# An IATA code is three letters (usually uppercase). Multi-city origins can be
# comma- or slash-separated (e.g. "LAX,JFK"). If the first arg matches this
# shape, we assume it's a flights search rather than a typo'd command.
_IATA_SHAPE = re.compile(r"^[A-Za-z]{3}([,/][A-Za-z]{3})*$")

# Register commands
app.command(name="flights")(flights)
app.command(name="dates")(dates)
app.command(name="hotels")(hotels)
app.command(name="hotel-price")(hotel_price)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Search for flights using Google Flights data.

    If no command is provided, show help.
    """
    if ctx.invoked_subcommand is None:
        ctx.get_help()
        raise typer.Exit()


def cli():
    """Entry point for the CLI that handles default command."""
    args = sys.argv[1:]
    if not args:
        sys.argv.append("--help")
        return app()

    first = args[0]
    if first in _KNOWN_COMMANDS or first in _HELP_FLAGS:
        return app()

    # Looks like a flights search (IATA code as first arg) — prepend the command.
    if _IATA_SHAPE.match(first):
        sys.argv.insert(1, "flights")
        return app()

    # Anything else (typo'd command, unknown subcommand) — show the top-level
    # help so users discover `hotels`, `hotel-price`, etc. instead of seeing
    # a confusing "Missing argument 'DESTINATION'" from the flights command.
    typer.echo(f"Error: Unknown command '{first}'.\n", err=True)
    sys.argv = [sys.argv[0], "--help"]
    try:
        app()
    except SystemExit:
        pass
    raise SystemExit(2)


if __name__ == "__main__":
    cli()
