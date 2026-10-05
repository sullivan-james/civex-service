"""Decides when a project syncs, and does it.

Whoever hosts it (the server on a thread, `civex sync watch` in a terminal) calls
`tick()` every few seconds. A sync runs when

- someone asked for one (`request()`, the Sync now button),
- there are changes made here that the authority has not been sent, a few
  seconds after the last attempt (so a burst of edits goes in one round), or
- the interval has passed, to bring in other people's changes.

A failure backs off (doubling, up to 15 minutes) so a server that is down is not
hammered; a refusal that waiting cannot fix (a revoked token, a different
project) waits the full 15 minutes and keeps saying why. Pausing stops all of it.
The sync itself is `SyncService.sync`, which is safe to repeat and holds a lock so
two hosts never run at once.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from civex.config import Config
from civex.domain.sync import SyncError
from civex.services.sync_lock import SyncBusy

if TYPE_CHECKING:
    from civex.context import AppContext
    from civex.services.sync_service import SyncReport

log = logging.getLogger(__name__)

DEBOUNCE = 3.0
BASE_BACKOFF = 5.0
MAX_BACKOFF = 900.0


class SyncWorker:
    def __init__(
        self,
        load_config: Callable[[], Config],
        open_context: Callable[[Config], AppContext],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._load_config = load_config
        self._open = open_context
        self._clock = clock
        self._requested = threading.Event()
        self._failures = 0
        self._backoff_until = 0.0
        self._next_interval = 0.0
        self._last_attempt = -DEBOUNCE

    def request(self) -> None:
        """Ask for a sync at the next tick, whatever the schedule says."""
        self._requested.set()

    def tick(self) -> SyncReport | None:
        """Sync if one is due. Returns what it did, or None when nothing ran
        (nothing due, paused, no authority, busy, or it failed: the reason is
        saved on the project and shown by `civex sync status`)."""
        config = self._load_config()
        if not config.sync.remote:
            self._requested.clear()
            return None
        if config.sync.paused and not self._requested.is_set():
            return None  # pausing stops the schedule; asking for one still works
        ctx = self._open(config)
        try:
            return self._maybe_sync(ctx, config)
        finally:
            ctx.close()

    def _maybe_sync(self, ctx: AppContext, config: Config) -> SyncReport | None:
        now = self._clock()
        asked = self._requested.is_set()
        waiting = now >= self._backoff_until
        due = asked or (
            waiting
            and (
                now >= self._next_interval
                or (
                    now - self._last_attempt >= DEBOUNCE
                    and ctx.sync_repo.count_pending() > 0
                )
            )
        )
        if not due:
            return None
        self._requested.clear()
        self._last_attempt = now
        try:
            report = ctx.sync_svc.sync()
        except SyncBusy:
            return None
        except SyncError as e:
            self._failures += 1
            wait = (
                MAX_BACKOFF
                if not e.retryable
                else min(MAX_BACKOFF, BASE_BACKOFF * 2**self._failures)
            )
            self._backoff_until = now + wait
            self._next_interval = now + config.sync.interval_seconds
            log.warning("sync failed (%s); trying again in %ds", e, wait)
            return None
        self._failures = 0
        self._backoff_until = 0.0
        self._next_interval = now + config.sync.interval_seconds
        return report

    def run(self, stop: threading.Event, poll: float = 2.0) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - one bad tick must not end syncing
                log.exception("sync tick failed")
            stop.wait(poll)
