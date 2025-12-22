#!/usr/bin/env python3
"""CLI entry point for the fli flight search tool."""

import sys

import typer

from fli.cli.commands.dates import dates
from fli.cli.commands.flights import flights

app = typer.Typer(
    help="Search for flights using Google Flights data",
    add_completion=True,
)

# Register commands
app.command(name="flights")(flights)
app.command(name="dates")(dates)


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
        args.append("--help")

    # If the first argument isn't a command, treat as flights search
    if args[0] not in ["flights", "dates", "--help", "-h"]:
        sys.argv.insert(1, "flights")

    app()


if __name__ == "__main__":
    cli()
