"""Decides when a project syncs, and does it.

Whoever hosts it (the server on a thread, `civex sync watch` in a terminal) calls
`tick()` every few seconds. A sync runs when

- someone asked for one (`request()`, the Sync now button),
- there are changes made here that the authority has not been sent, a few
  seconds after the last attempt (so a burst of edits goes in one round), or
- the interval has passed, to bring in other people's changes.

With the interval set to never, only a request syncs. A project that joined an
authority fetches the history from before it joined a few pages per tick after
that, so it never holds up a sync, and then (with `[sync] download_files` at
"all", the default) the files its records cite that aren't here, for up to
`FILES_SECONDS` a tick. A failure backs off (doubling, up to 15 minutes) so a server that is down is not
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
from civex.domain.sync import FILES, SyncError, SyncProgress
from civex.services.sync_lock import SyncBusy

if TYPE_CHECKING:
    from civex.context import AppContext
    from civex.services.sync_service import SyncReport

log = logging.getLogger(__name__)

DEBOUNCE = 3.0
# The look for files the authority lacks costs a request per thousand files, so a
# background sync does it this often (a manual sync always does).
FILE_CHECK_EVERY = 600.0
BASE_BACKOFF = 5.0
MAX_BACKOFF = 900.0
# Pages of history from before joining fetched per tick (200 entries a page).
HISTORY_PAGES = 10
# How long a tick spends downloading files before it lets a sync run again (it
# stops between files, so one large file can take longer).
FILES_SECONDS = 20.0

ProgressSink = Callable[[SyncProgress | None], None]


class SyncWorker:
    def __init__(
        self,
        load_config: Callable[[], Config],
        open_context: Callable[[Config], AppContext],
        clock: Callable[[], float] = time.monotonic,
        on_progress: ProgressSink | None = None,
    ) -> None:
        self._load_config = load_config
        self._open = open_context
        self._clock = clock
        # Told how far a long step has got, and None when it is done.
        self._on_progress = on_progress or (lambda _: None)
        self._requested = threading.Event()
        self._failures = 0
        self._backoff_until = 0.0
        self._next_interval = 0.0
        self._last_attempt = -DEBOUNCE
        self._last_file_check = -FILE_CHECK_EVERY
        # Files the authority didn't have when asked (the device that added
        # them hasn't sent them yet): not asked for again until the next look
        # for files. And how far the current run of downloads has got, for the
        # progress shown (the number to fetch when it began, and done since).
        self._absent: set[str] = set()
        self._absent_since = 0.0
        self._files_total = 0
        self._files_done = 0
        # What the last sync run here did, for the app to report. Kept in memory:
        # it is a notice, not state anyone needs after a restart.
        self.last_report: SyncReport | None = None

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
            report = self._maybe_sync(ctx, config)
            if not config.sync.paused:
                self._fetch_history(ctx)
                # Only collections kept on this computer (see collection_mode):
                # the service limits it, so nothing is fetched when none are.
                self._fetch_files(ctx)
            return report
        finally:
            ctx.close()

    def _fetch_history(self, ctx: AppContext) -> None:
        """A few pages of the history from before this project joined, while
        any is still to come and the authority is answering."""
        if not ctx.sync_repo.meta().history_from:
            return
        if self._clock() < self._backoff_until:
            return
        try:
            if ctx.sync_svc.fetch_history(self._on_progress, pages=HISTORY_PAGES):
                self._on_progress(None)
        except SyncBusy:
            return
        except SyncError as e:
            log.info("fetching history failed (%s); it carries on later", e)

    def _fetch_files(self, ctx: AppContext) -> None:
        """Download files this project's records cite that aren't here, for a
        while, while the authority is answering."""
        now = self._clock()
        if now < self._backoff_until or ctx.sync_repo.meta().history_from:
            return
        if now - self._absent_since >= FILE_CHECK_EVERY:
            self._absent.clear()
            self._absent_since = now
        left = ctx.sync_svc.files_to_fetch() - len(self._absent)
        if left <= 0:
            if self._files_total:
                self._files_total = self._files_done = 0
                self._on_progress(None)
            return
        if not self._files_total:
            self._files_total, self._files_done = left, 0
        base = self._files_done

        def tell(done: int) -> None:
            self._files_done = base + done
            total = max(self._files_total, self._files_done)
            self._on_progress(SyncProgress(FILES, self._files_done, total))

        try:
            report = ctx.sync_svc.fetch_files(
                skip=self._absent, seconds=FILES_SECONDS, progress=tell
            )
        except SyncError as e:
            log.info("downloading files failed (%s); it carries on later", e)
            return
        self._absent.update(report.absent)
        if not report.stopped:  # all that could be fetched now is here
            self._files_total = self._files_done = 0
            self._on_progress(None)

    def _maybe_sync(self, ctx: AppContext, config: Config) -> SyncReport | None:
        now = self._clock()
        asked = self._requested.is_set()
        waiting = now >= self._backoff_until
        manual_only = config.sync.interval_seconds == 0
        due = asked or (
            not manual_only
            and waiting
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
        log.info("background sync: %s", "requested" if asked else "due")
        try:
            files = asked or now - self._last_file_check >= FILE_CHECK_EVERY
            report = ctx.sync_svc.sync(check_files=files)
            if files:
                self._last_file_check = now
            self.last_report = report
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
