"""How far a long request has got, for a client that is waiting on it.

A big selection takes a while to work out and to build, and the request that asks
for it says nothing until it ends. So the client tags the request with an id and
asks, from the side, how far along it is; the work updates a `Progress` as it goes.
It lives in memory in the one server process (like the move worker's live
numbers), is never saved, and is forgotten shortly after it finishes.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from civex.domain.rates import RateWindow, eta_seconds

# A client-chosen id: short and plain, so it can't be used to smuggle anything.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_KEEP_FINISHED_SECONDS = 120
_KEEP_UNTOUCHED_SECONDS = 3600


@dataclass
class _State:
    phase: str = ""
    done: int = 0
    total: int = 0
    finished: bool = False
    error: str | None = None
    touched: float = 0.0
    # For a stage that moves bytes (downloading): how many so far and of how
    # many (0 = not known), how fast, and how long the rest will take.
    bytes_done: int = 0
    bytes_total: int = 0
    rate: float = 0.0
    eta: float | None = None


class Progress:
    """What the work reports into. All methods are cheap and safe from any thread."""

    def __init__(self, state: _State, lock: threading.Lock) -> None:
        self._state = state
        self._lock = lock
        self._rate = RateWindow()

    def phase(self, label: str, total: int = 0, total_bytes: int = 0) -> None:
        """A new stage of the work, with how many steps it has (0 = not known)
        and, for one that moves bytes, how many."""
        with self._lock:
            self._state.phase = label
            self._state.done = 0
            self._state.total = max(total, 0)
            self._state.bytes_done = 0
            self._state.bytes_total = max(total_bytes, 0)
            self._state.rate = 0.0
            self._state.eta = None
            self._state.touched = time.monotonic()
        self._rate = RateWindow()

    def add_bytes(self, n: int) -> None:
        """Bytes that have just arrived (or moved) in this stage."""
        with self._lock:
            now = time.monotonic()
            self._state.bytes_done += n
            self._state.rate = self._rate.add(now, self._state.bytes_done)
            self._state.eta = eta_seconds(
                self._state.rate, self._state.bytes_done, self._state.bytes_total
            )
            self._state.touched = now

    def advance(self, done: int, total: int | None = None) -> None:
        """Steps done so far in this stage (and, if it has just become known, how many
        there are)."""
        with self._lock:
            self._state.done = done
            if total is not None:
                self._state.total = max(total, 0)
            self._state.touched = time.monotonic()

    def finish(self, error: str | None = None) -> None:
        with self._lock:
            self._state.finished = True
            self._state.error = error
            self._state.touched = time.monotonic()


class ProgressRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, _State] = {}

    @staticmethod
    def valid(progress_id: str | None) -> bool:
        return bool(progress_id and _ID_RE.match(progress_id))

    def start(self, progress_id: str) -> Progress:
        """Begin reporting under `progress_id` (which must be `valid`)."""
        with self._lock:
            self._forget_old()
            state = self._states[progress_id] = _State(touched=time.monotonic())
        return Progress(state, self._lock)

    def get(self, progress_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._states.get(progress_id)
            if state is None:
                return None
            return {
                "phase": state.phase,
                "done": state.done,
                "total": state.total,
                "finished": state.finished,
                "error": state.error,
                "bytes_done": state.bytes_done,
                "bytes_total": state.bytes_total,
                "rate": state.rate,
                "eta": state.eta,
            }

    def _forget_old(self) -> None:
        now = time.monotonic()
        for pid, state in list(self._states.items()):
            age = now - state.touched
            if (state.finished and age > _KEEP_FINISHED_SECONDS) or (
                age > _KEEP_UNTOUCHED_SECONDS
            ):
                del self._states[pid]


registry = ProgressRegistry()
