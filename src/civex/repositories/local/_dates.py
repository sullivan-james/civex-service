"""Date helpers shared by the local repositories."""

from __future__ import annotations

from datetime import datetime, timezone

from civex.domain.exceptions import ValidationError


def utc(value: object) -> datetime:
    """A filter's date, as the UTC instant the column holds."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(f"Not a date: {value!r}")
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )
