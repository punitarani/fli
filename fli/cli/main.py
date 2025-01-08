#!/usr/bin/env python3

import sys

import typer

from fli.cli.commands.cheap import cheap
from fli.cli.commands.search import search

app = typer.Typer(
    help="Search for flights using Google Flights data",
    add_completion=True,
)

# Register commands
app.command(name="search")(search)
app.command(name="cheap")(cheap)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Search for flights using Google Flights data.

    If no command is provided, the search command will be used.
    """
    # If no command is provided, show help
    if ctx.invoked_subcommand is None:
        ctx.get_help()
        raise typer.Exit()


def cli():
    """Entry point for the CLI that handles default command."""
    args = sys.argv[1:]
    if not args:
        app()
        return

    # If the first argument isn't a command, treat as search
    if args[0] not in ["search", "cheap", "--help", "-h"]:
        sys.argv.insert(1, "search")

    app()


if __name__ == "__main__":
    cli()
