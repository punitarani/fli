"""Shared error-formatting utilities for the CLI and MCP interfaces.

Pydantic's default ``str(ValidationError)`` is a multi-line dump meant for
developers, not end users or AI assistants driving the MCP tools. Both
interfaces need the same one-line, actionable rendering of "what exactly is
wrong" — this module keeps that logic in one place.
"""

from pydantic import ValidationError


def format_validation_error(exc: ValidationError) -> str:
    """Flatten a pydantic ``ValidationError`` into one actionable message.

    The underlying validators already say exactly what is wrong (e.g. "Total
    passengers must be between 1 and 9"); without this, callers only ever saw
    a multi-line pydantic dump, which gives nothing to act on.
    """
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "input"
        problems.append(f"{location}: {error['msg']}")
    return f"Invalid parameter value - {'; '.join(problems)}"
