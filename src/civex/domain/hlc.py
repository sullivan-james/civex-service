"""A hybrid logical clock: timestamps that sort in causal order.

A change is stamped `<wall milliseconds>.<counter>`: the wall clock when it is
moving forward, the counter to keep stamps strictly increasing when it is not
(two changes in one millisecond, or a clock set back). Both parts are
zero-padded, so stamps compare correctly as plain strings. Pure: callers pass
the clock in.
"""

from __future__ import annotations

_WALL_DIGITS = 13  # milliseconds since 1970 stays 13 digits until the year 2286
_COUNTER_DIGITS = 4


def format_stamp(wall_ms: int, counter: int) -> str:
    return f"{wall_ms:0{_WALL_DIGITS}d}.{counter:0{_COUNTER_DIGITS}d}"


def parse_stamp(stamp: str) -> tuple[int, int]:
    wall, _, counter = stamp.partition(".")
    return int(wall), int(counter or 0)


def tick(last: str | None, wall_ms: int) -> str:
    """The stamp for a change made now, after `last` (None if there is none)."""
    if last is None:
        return format_stamp(wall_ms, 0)
    last_wall, last_counter = parse_stamp(last)
    if wall_ms > last_wall:
        return format_stamp(wall_ms, 0)
    return format_stamp(last_wall, last_counter + 1)


def receive(last: str | None, seen: str, wall_ms: int) -> str:
    """The stamp to carry on from after seeing `seen` from elsewhere, so a
    change made here afterwards sorts after it however the clocks differ."""
    seen_wall, seen_counter = parse_stamp(seen)
    last_wall, last_counter = parse_stamp(last) if last else (0, 0)
    top = max(wall_ms, seen_wall, last_wall)
    if top == wall_ms and wall_ms > seen_wall and wall_ms > last_wall:
        return format_stamp(wall_ms, 0)
    counters = [
        c for w, c in ((seen_wall, seen_counter), (last_wall, last_counter)) if w == top
    ]
    return format_stamp(top, max(counters, default=0) + 1)
