"""Time-ordered identifiers for the tables that take the most inserts.

A random (v4) primary key sends every insert to a random leaf of every index
that contains it. Once those indexes are larger than memory that is a cache
miss plus, after each checkpoint, a full-page WAL image per row: measured at
20M rows it was 10x slower and wrote 8x more WAL than ids that rise with time
(civex-service PR #418, docs/contributing/billion-row-collections.md).

Two generators, both pure Python (`uuid.uuid7` only arrives in Python 3.14)
and independent of the database, so SQLite and PostgreSQL behave the same:

- `uuid7()`: RFC 9562 UUIDv7, a 48-bit millisecond timestamp first. Perfectly
  append-only, but the first 8 hex characters (what people type and civex
  prints as a short id) are then the same for every row made in the same
  65 seconds, and the creation time of a row is readable from its id.
- `row_id()`: what the busy tables use. RFC 9562 UUIDv8 (custom layout) whose
  first 32 bits are the microsecond clock modulo 2**32. Ids rise with time and
  wrap every 71.6 minutes, so consecutive inserts still land next to each
  other in an index (a sweep through it, not a random leaf per row), yet the
  first 8 hex characters stay as distinct as a random id's: the short-id
  prefix that civex's CLI and UI print and accept keeps working, and only the
  time of day modulo 71.6 minutes can be read from an id, not when it was made.

Ids stay opaque UUIDs everywhere else (same type, same wire format, same
column), rows written before this existed keep their v4 ids, and the three mix
freely. Ids made by this process never go backwards within a lap, even if the
clock does.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone

_lock = threading.Lock()
_last_ms = -1
_counter = 0  # 12-bit rand_a, used as a counter within one millisecond


def uuid7() -> uuid.UUID:
    """A new UUIDv7: 48-bit unix ms, version, 12-bit counter, variant, 62 random bits.

    Strictly increasing within the process (RFC 9562 section 6.2, method 1):
    inside one millisecond the 12-bit field counts up from a random start; if
    it would overflow, or the clock stepped back, the timestamp is advanced by
    one millisecond instead of repeating or regressing.
    """
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms = ms
            # Start below the top of the range so a burst has room to count.
            _counter = int.from_bytes(os.urandom(2), "big") & 0x7FF
        else:
            _counter += 1
            if _counter > 0xFFF:
                _last_ms += 1
                _counter = int.from_bytes(os.urandom(2), "big") & 0x7FF
        stamp, count = _last_ms, _counter
    tail = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (stamp & 0xFFFFFFFFFFFF) << 80 | 0x7 << 76 | count << 64 | 0b10 << 62 | tail
    return uuid.UUID(int=value)


def id_time(value: uuid.UUID) -> datetime | None:
    """When a UUIDv7 was made, or None for any other version (a v4 id says nothing)."""
    if value.version != 7:
        return None
    return datetime.fromtimestamp((value.int >> 80) / 1000, tz=timezone.utc)


_us_lock = threading.Lock()
_last_us = -1  # unwrapped microseconds of the newest row_id
_us_counter = 0  # 16 bits, used inside one microsecond


def row_id() -> uuid.UUID:
    """A new time-ordered UUIDv8 for a row: 32-bit wrapping microsecond clock,
    16-bit counter, version 8, 12 random bits, variant, 62 random bits.

    Rising within the process (inside a microsecond the counter counts up; if
    it would overflow, or the clock stepped back, the time is advanced by one
    microsecond instead of repeating or regressing) except at the wrap, once
    every 2**32 microseconds, when the first 32 bits start again from zero.
    """
    global _last_us, _us_counter
    with _us_lock:
        us = time.time_ns() // 1000
        if us > _last_us:
            _last_us = us
            _us_counter = int.from_bytes(os.urandom(2), "big") & 0x7FFF
        else:
            _us_counter += 1
            if _us_counter > 0xFFFF:
                _last_us += 1
                _us_counter = int.from_bytes(os.urandom(2), "big") & 0x7FFF
        stamp, count = _last_us & 0xFFFFFFFF, _us_counter
    tail = int.from_bytes(os.urandom(9), "big") & ((1 << 74) - 1)
    value = (
        stamp << 96
        | count << 80
        | 0x8 << 76
        | (tail >> 62) << 64  # 12 random bits
        | 0b10 << 62
        | (tail & ((1 << 62) - 1))
    )
    return uuid.UUID(int=value)
