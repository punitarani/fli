"""Helper for building the search-page bodies the transport now parses.

Since the move to the public ``/travel/flights`` page, the client reads its
payload out of an ``AF_initDataCallback`` blob keyed ``ds:1`` rather than a
``wrb.fr`` RPC body. Tests that fake a response wrap their payload here.
"""

from __future__ import annotations

import json
from typing import Any


def as_search_page(payload: Any) -> str:
    """Wrap ``payload`` as the ``ds:1`` blob of a rendered search page."""
    return (
        "<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:"
        + json.dumps(payload, separators=(",", ":"))
        + ", sideChannel: {}});</script>"
    )
