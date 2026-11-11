"""Display helpers for the generated ``Airport`` / ``Airline`` enums."""

from .airline import Airline
from .airport import Airport


def display_name(member: Airport | Airline) -> str:
    """Return a member's human-readable name as it should be shown to users.

    Enum values must be unique, so names shared by several members are stored
    with a disambiguating `` (CODE)`` suffix (see ``scripts/generate_enums.py``).
    That suffix is an internal detail: the code is always presented separately,
    so it is stripped here.

    Args:
        member: An ``Airport`` or ``Airline`` enum member.

    Returns:
        The name without any `` (CODE)`` suffix, e.g. ``"Naha Airport"`` for
        both ``Airport.NAH`` and ``Airport.OKA``.

    """
    code = member.name.removeprefix("_")
    return member.value.removesuffix(f" ({code})")
