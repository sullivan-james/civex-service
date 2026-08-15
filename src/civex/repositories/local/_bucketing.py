"""Shared SQL/Python helpers for the analytics repositories' day-granularity
GROUP BYs and their Python-side roll-up into week/month buckets.

Grouping happens in SQL at day granularity (portable across SQLite and
PostgreSQL via `func.date`); coarser buckets are derived in Python by
re-keying and summing the day rows, since dialect-portable week/month
truncation has no single SQL builtin. The number of day-groups is bounded
by the query's date range, not row count, so this stays cheap even for a
wide range.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import Date, func


def day_bucket(column: Any) -> Any:
    """Truncate a UTC datetime column to its calendar day. Explicitly typed
    as Date so SQLAlchemy hands back a plain `datetime.date` on both SQLite
    (which returns the DATE() text form) and PostgreSQL (which returns a
    native date) -- callers never need dialect-specific handling.
    """
    return func.date(column, type_=Date)


def bucket_start(day: date, bucket: str) -> str:
    """The ISO date string of the bucket `day` falls into for the given
    bucket size."""
    if bucket == "day":
        return day.isoformat()
    if bucket == "week":
        return (day - timedelta(days=day.weekday())).isoformat()
    if bucket == "month":
        return day.replace(day=1).isoformat()
    raise ValueError(f"Unknown bucket size: {bucket!r}")


def rebucket(rows: list[tuple], bucket: str) -> list[tuple]:
    """Re-key day-granular `(day, *dims, count)` rows into the requested
    bucket size, summing counts for rows that land in the same bucket.
    `day` must be the first element and `count` the last; any number of
    dimension columns may sit between them."""
    merged: dict[tuple, int] = {}
    for row in rows:
        day, *dims, count = row
        key = (bucket_start(day, bucket), *dims)
        merged[key] = merged.get(key, 0) + count
    return sorted((*key, count) for key, count in merged.items())
