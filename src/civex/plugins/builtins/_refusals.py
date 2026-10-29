"""When a built-in skips a row instead of failing the run.

Built-ins reach the project through the host functions like any plugin, so
a write the host refuses comes back as an `RpcError` carrying the refusal's
kind (`civex.domain.exceptions`). A row whose values a field doesn't allow,
or that would duplicate a unique key, is skipped and reported; anything else
(a broken connection, a capability not granted) fails the run.
"""

from __future__ import annotations

from civex_plugin_sdk import RpcError

#: A ValidationError of any sort, DuplicateRecordError included.
REFUSED = frozenset({"validation_error", "duplicate_record"})
#: The record asked for is gone (deleted meanwhile).
GONE = "not_found"


def refused(e: RpcError, *also: str) -> bool:
    """Whether `e` is the host refusing this one write (or one of `also`)."""
    return e.kind in REFUSED or e.kind in also
