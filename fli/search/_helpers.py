"""Small structural helpers shared by the response decoders.

Kept narrow on purpose — every helper is a one-line defensive accessor over
the raw nested-list responses returned by Google Flights' RPC endpoints.
Keeping them in one place lets the decoders read like a list of position
look-ups rather than nested defensive code.
"""

from __future__ import annotations

from typing import Any


def safe_get(seq: Any, idx: int) -> Any:
    """Return ``seq[idx]`` when ``seq`` is a list and idx is in range, else None."""
    if isinstance(seq, list) and 0 <= idx < len(seq):
        return seq[idx]
    return None


def as_bool(v: Any) -> bool | None:
    """Return ``v`` only if it is a Python bool — None for any other type.

    Useful because Google encodes many tri-state fields as bool|None and we
    want to preserve the "None means unknown" distinction.
    """
    return v if isinstance(v, bool) else None


def as_str(v: Any) -> str | None:
    """Return ``v`` only if it is a non-empty string, else None."""
    return v if isinstance(v, str) and v else None


def as_int(v: Any) -> int | None:
    """Return ``v`` only if it is an integer (and not a bool, which Python treats as int)."""
    if isinstance(v, bool):
        return None
    return v if isinstance(v, int) else None


def as_non_negative_int(v: Any) -> int | None:
    """Return ``v`` only if it is an integer ≥ 0, else None."""
    n = as_int(v)
    return n if n is not None and n >= 0 else None
