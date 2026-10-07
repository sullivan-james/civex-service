"""How fast bytes are moving, and how long the rest will take: the one rule for
every transfer a person watches (moving files between drives, downloading
them from a server).

The speed is over the last `RATE_WINDOW` seconds, not since the start, so it
follows the real pace (a slow first file doesn't drag it down for minutes).
"""

from __future__ import annotations

from collections import deque

RATE_WINDOW = 15.0  # seconds of history the speed is averaged over


class RateWindow:
    def __init__(self, window: float = RATE_WINDOW) -> None:
        self._window = window
        self._points: deque[tuple[float, int]] = deque()

    def add(self, now: float, done: int) -> float:
        """Record `done` bytes so far at `now`; returns bytes per second."""
        self._points.append((now, done))
        while len(self._points) > 2 and now - self._points[0][0] > self._window:
            self._points.popleft()
        t0, b0 = self._points[0]
        return max((done - b0) / (now - t0), 0.0) if now - t0 > 0 else 0.0


def eta_seconds(rate: float, done: int, total: int | None) -> float | None:
    """Seconds left at this rate; None when it can't be said."""
    remaining = max((total or 0) - done, 0)
    return remaining / rate if rate > 0 and remaining else None
