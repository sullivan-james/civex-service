"""Id helpers shared by the local repositories."""

from __future__ import annotations

import uuid


def prefix_span(prefix: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """The lowest and highest ids that start with `prefix` (hex, dashes
    optional), or None when nothing can: not hex, or longer than an id."""
    digits = prefix.lower().replace("-", "")
    if (
        not digits
        or len(digits) > 32
        or any(c not in "0123456789abcdef" for c in digits)
    ):
        return None
    pad = 32 - len(digits)
    return uuid.UUID(digits + "0" * pad), uuid.UUID(digits + "f" * pad)
