"""Timezones for datetime fields.

Datetimes are always *stored* as UTC instants. A timezone only matters in two
places: reading a value that carries no offset ("2024-03-01T15:30" -- the
instrument export, the CSV cell, the filename stamp), and showing a stored
instant back as wall time. Both resolve the zone the same way: a field's own
``timezone`` restriction wins, then its collection's ``timezone``, then
nothing (naive input is read as UTC; the UI falls back to the viewer's own
zone).

Wall times that clocks skip or repeat are rejected rather than guessed --
silently picking one shifts a measurement by an hour, which is exactly the
kind of error a dataset can't afford. An explicit offset ("...-05:00") always
sidesteps the problem.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as _tz
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from civex.domain.exceptions import ValidationError


def validate_timezone(name: str) -> str:
    """Return *name* stripped if it is a known IANA zone, else raise."""
    cleaned = name.strip()
    try:
        if not cleaned:
            raise ValueError("empty")
        ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValidationError(
            f"Unknown timezone '{name}'. Use an IANA name such as "
            "'America/Chicago' or 'UTC'."
        ) from None
    return cleaned


def localize(naive: datetime, tz: str) -> datetime:
    """Interpret a naive wall time in *tz*; return the UTC instant.

    Raises ValidationError if the wall time doesn't exist (clocks spring
    forward over it) or is ambiguous (clocks fall back through it twice).
    """
    zone = ZoneInfo(tz)
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    off_first, off_second = first.utcoffset(), second.utcoffset()
    if off_first != off_second:
        assert off_first is not None and off_second is not None
        if off_first > off_second:
            problem = "is ambiguous (clocks go back, so it happens twice)"
        else:
            problem = "does not exist (clocks skip forward over it)"
        raise ValidationError(
            f"{naive.isoformat(timespec='minutes')} {problem} in {tz}. "
            "Include a UTC offset, e.g. 2024-11-03T01:30-05:00."
        )
    return first.astimezone(_tz.utc)


def parse_datetime(raw: str, tz: str | None = None) -> str:
    """Normalise *raw* to a UTC ISO string.

    A value with an offset is converted as-is. A value without one is read as
    wall time in *tz*, or as UTC when *tz* is None -- the long-standing
    default, kept for collections that never set a zone.
    """
    s = raw.strip()
    # datetime-local inputs omit seconds
    if len(s) == 16 and s[10] == "T":
        s += ":00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = localize(dt, tz) if tz else dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(_tz.utc).isoformat()


# The years `offset_changes` looks at: a value outside them keeps the offset
# of the nearest end (a zone's rules beyond 2100 are a guess anyway).
OFFSET_YEARS = (1900, 2100)


@lru_cache(maxsize=32)
def offset_changes(tz: str) -> tuple[int, tuple[tuple[datetime, int], ...]]:
    """*tz*'s offset from UTC in minutes before its first change in
    `OFFSET_YEARS`, then each change: the UTC instant it happens at (naive)
    and the offset from then on. What a database without time zones (SQLite)
    needs to read a stored UTC instant as wall time in *tz*: one CASE over
    these instants, the same answers as `ZoneInfo`. Worked out once a zone
    (a day at a time, then to the minute inside the day it changes)."""
    zone = ZoneInfo(tz)

    def offset(at: datetime) -> int:
        delta = at.replace(tzinfo=_tz.utc).astimezone(zone).utcoffset()
        return int(delta.total_seconds() // 60) if delta else 0

    start = datetime(OFFSET_YEARS[0], 1, 1)
    end = datetime(OFFSET_YEARS[1], 1, 1)
    first = current = offset(start)
    changes: list[tuple[datetime, int]] = []
    day = start
    while day < end:
        nxt = day + timedelta(days=1)
        if offset(nxt) != current:
            lo, hi = day, nxt  # offset(lo) == current, offset(hi) != current
            while hi - lo > timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                mid = mid.replace(second=0, microsecond=0)
                if mid <= lo:
                    mid = lo + timedelta(minutes=1)
                if offset(mid) == current:
                    lo = mid
                else:
                    hi = mid
            current = offset(hi)
            changes.append((hi, current))
        day = nxt
    return first, tuple(changes)
