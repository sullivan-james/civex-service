"""How big one page of a sync read may be, decided in one place.

Every paged read (the feed, a snapshot, a history page) is limited twice: by a
count of things (`limit`, an "at most") and by a byte budget of the payload they
carry, so a page of wide records stops early instead of being a 60 MB answer.
`more` is computed here and nowhere else: it is "the page stopped before the
end of what there is", so a page cut for any reason says there is more."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

# Payload bytes (old_data/new_data/delta, or the serialised thing) one page may
# carry. A page always holds at least one thing, however big it is.
PAGE_BUDGET_BYTES = 2 * 1024 * 1024
# A feed page keeps an action whole past `limit` while it fits: at most this
# many entries.
ACTION_ENTRIES_MAX = 5000


def budget() -> int:
    """The page budget in force (read when asked, so one setting rules every
    paged read)."""
    return PAGE_BUDGET_BYTES


def fit(sizes: Sequence[int], limit: int, max_bytes: int | None = None) -> int:
    """How many of the leading things fit a page: at most `limit`, at most
    `max_bytes` of payload, and at least one (a thing over the budget on its
    own still travels, alone)."""
    max_bytes = budget() if max_bytes is None else max_bytes
    used = 0
    for n, size in enumerate(sizes[:limit]):
        if n and used + size > max_bytes:
            return n
        used += size
    return min(len(sizes), limit)


def take(
    items: Sequence[Any],
    sizes: Sequence[int],
    limit: int,
    max_bytes: int | None = None,
) -> tuple[list[Any], bool]:
    """The page, and whether more follow. `items` is what was read past the
    cursor, one beyond `limit` if that many exist: the page is a prefix of
    it, and `more` is whether it stopped before the end of what was read."""
    n = fit(sizes, limit, max_bytes)
    return list(items[:n]), n < len(items)


def json_size(value: Any) -> int:
    """The serialised size of a thing, for those read as objects."""
    return len(json.dumps(value, default=str, separators=(",", ":")))
