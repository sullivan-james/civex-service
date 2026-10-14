"""Decides when a project syncs, and does it.

Whoever hosts it (the server on a thread, `civex sync watch` in a terminal) calls
`tick()` every few seconds. A sync runs when

- someone asked for one (`request()`, the Sync now button),
- there are changes made here that the authority has not been sent, a few
  seconds after the last attempt (so a burst of edits goes in one round), or
- the interval has passed, to bring in other people's changes.

With the interval set to never, only a request syncs. A project that joined an
authority fetches the history from before it joined a few pages per tick after
that, so it never holds up a sync. A failure backs off (doubling, up to 15
minutes) so a server that is down is not hammered; a refusal that waiting cannot
fix (a revoked token, a different project) waits the full 15 minutes and keeps
saying why. Pausing stops all of it. The sync itself is `SyncService.sync`, which
is safe to repeat and holds a lock so two hosts never run at once.

**Files are not part of a sync.** A sync moves the project's data only; files
go on a loop of their own (`files_tick`, on its own thread in `run`), so a
large upload never holds up a change and a change never waits for a file: it
sends what the authority lacks (`SyncService.send_files`), then (with `[sync]
download_files` at "all", the default) fetches what is cited and not here, for
up to `FILES_SECONDS` each a tick.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from civex.config import Config
from civex.domain.rates import RateWindow
from civex.domain.sync import FILES, SyncError, SyncProgress
from civex.services.sync_lock import SyncBusy

if TYPE_CHECKING:
    from civex.context import AppContext
    from civex.services.sync_service import SyncReport

log = logging.getLogger(__name__)

DEBOUNCE = 3.0
# Files the authority has said it holds aren't asked about again, except this
# often (and on a manual sync), in case one it held has gone.
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
        on_files: ProgressSink | None = None,
    ) -> None:
        self._load_config = load_config
        self._open = open_context
        self._clock = clock
        # Told how far a long step has got, and None when it is done.
        self._on_progress = on_progress or (lambda _: None)
        # The same for files going up or coming down, which run beside a sync.
        self._on_files = on_files or self._on_progress
        self._requested = threading.Event()
        # Downloading what this computer keeps was asked for (a collection was
        # just set to keep its files here): done first, before any sync.
        self._files_asked = threading.Event()
        # Sending files was asked for (Send now, a manual sync): every file is
        # asked about again, at the next files tick.
        self._send_asked = threading.Event()
        # Set by a request, so a loop doesn't sleep through it: one for the
        # sync loop, one for the files loop.
        self._wake = threading.Event()
        self._files_wake = threading.Event()
        # When the files loop last failed to reach the authority: it waits a
        # while before trying again, like a sync.
        self._files_backoff_until = 0.0
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

    def request_files(self, total: int = 0) -> None:
        """Start downloading what this computer keeps now, ahead of any sync.
        With `total` (how many are missing), the progress is published at once,
        before the worker has woken, so the status bar shows it on its next
        read rather than after the first file has arrived."""
        if total > 0:
            self._files_total, self._files_done = total, 0
            self._on_files(SyncProgress(FILES, 0, total))
        self._files_asked.set()
        self._files_wake.set()

    def request_send(self) -> None:
        """Send files the authority lacks now (Send now), asking it about
        every file again."""
        self._send_asked.set()
        self._files_wake.set()

    def request(self) -> None:
        """Ask for a sync at the next tick, whatever the schedule says. Files
        are looked at again too (a person asking wants everything up to date)."""
        self._requested.set()
        self._wake.set()
        self.request_send()

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
            return report
        finally:
            ctx.close()

    def files_tick(self) -> None:
        """Move files, beside syncing: send what the authority lacks, then
        fetch what this computer keeps and hasn't got. Each for a while at
        most, so a pause or a change of settings is noticed between files."""
        config = self._load_config()
        if not config.sync.remote:
            self._files_asked.clear()
            self._send_asked.clear()
            return
        asked = self._files_asked.is_set()
        sending = self._send_asked.is_set()
        if config.sync.paused and not (asked or sending):
            return
        self._files_asked.clear()
        self._send_asked.clear()
        if not (asked or sending) and self._clock() < self._files_backoff_until:
            return
        ctx = self._open(config)
        try:
            if not asked or sending:
                self._send_files(ctx, everything=sending)
            # Only collections kept on this computer (see collection_mode):
            # the service limits it, so nothing is fetched when none are.
            self._fetch_files(ctx, asked=asked)
        finally:
            ctx.close()

    def _send_files(self, ctx: AppContext, everything: bool) -> None:
        """Upload, for a while, the files the authority hasn't said it holds
        (every file it is asked about again, when `everything` or every
        `FILE_CHECK_EVERY`)."""
        now = self._clock()
        everything = everything or now - self._last_file_check >= FILE_CHECK_EVERY
        sending = False

        def told(p: SyncProgress) -> None:
            nonlocal sending
            sending = True
            self._on_files(p)

        try:
            report = ctx.sync_svc.send_files(
                everything=everything, seconds=FILES_SECONDS, progress=told
            )
        except SyncError as e:
            log.info("sending files failed (%s); it carries on later", e)
            self._files_backoff_until = now + MAX_BACKOFF / 5
            if sending:
                self._on_files(None)
            return
        if everything:
            self._last_file_check = now
        if sending and not report.stopped:  # no bar left where uploading ended
            self._on_files(None)
        if report.stopped:
            self._files_wake.set()  # more to send: carry on at once

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

    def _fetch_files(self, ctx: AppContext, asked: bool = False) -> None:
        """Download files this project's records cite that aren't here, for a
        while, while the authority is answering (or at once, when `asked`)."""
        now = self._clock()
        waiting = now < self._files_backoff_until and not asked
        if waiting or ctx.sync_repo.meta().history_from:
            return
        if now - self._absent_since >= FILE_CHECK_EVERY:
            self._absent.clear()
            self._absent_since = now
        left = ctx.sync_svc.files_to_fetch() - len(self._absent)
        if left <= 0:
            if self._files_total:
                self._files_total = self._files_done = 0
                self._on_files(None)
            return
        if not self._files_total:
            self._files_total, self._files_done = left, 0
        base = self._files_done
        # Said before the first file starts (one can take minutes), so a person
        # sees at once that it is under way and how many there are.
        self._on_files(SyncProgress(FILES, base, max(self._files_total, base)))

        rate = RateWindow()
        got = [0]  # bytes so far in this pass

        def say() -> None:
            total = max(self._files_total, self._files_done)
            self._on_files(
                SyncProgress(
                    FILES,
                    self._files_done,
                    total,
                    bytes_done=got[0],
                    rate=rate.add(self._clock(), got[0]),
                )
            )

        def tell(done: int) -> None:
            self._files_done = base + done
            say()

        def arrived(n: int) -> None:
            got[0] += n
            say()

        try:
            report = ctx.sync_svc.fetch_files(
                skip=self._absent,
                seconds=FILES_SECONDS,
                progress=tell,
                on_bytes=arrived,
            )
        except SyncError as e:
            log.info("downloading files failed (%s); it carries on later", e)
            # Nothing is moving: no bar stuck where it was. The failure is
            # what the next sync reports.
            self._files_total = self._files_done = 0
            self._on_files(None)
            self._files_backoff_until = now + MAX_BACKOFF / 5
            return
        self._absent.update(report.absent)
        if not report.stopped:  # all that could be fetched now is here
            self._files_total = self._files_done = 0
            self._on_files(None)
        else:
            self._files_wake.set()  # more to fetch: carry on at once

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
            report = ctx.sync_svc.sync()
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
        """Sync on this thread and move files on another until `stop`, so a
        file taking minutes never holds up a change."""
        files = threading.Thread(
            target=self.run_files, args=(stop, poll), daemon=True, name="sync-files"
        )
        files.start()
        try:
            self._loop(stop, poll, self.tick, self._wake, "sync tick failed")
        finally:
            self._files_wake.set()
            files.join(5.0)

    def run_files(self, stop: threading.Event, poll: float = 2.0) -> None:
        self._loop(stop, poll, self.files_tick, self._files_wake, "files tick failed")

    @staticmethod
    def _loop(
        stop: threading.Event,
        poll: float,
        tick: Callable[[], object],
        wake: threading.Event,
        what: str,
    ) -> None:
        while not stop.is_set():
            try:
                tick()
            except Exception:  # noqa: BLE001 - one bad tick must not end syncing
                log.exception(what)
            # Sleep until the next look, or until someone asks for something.
            wake.wait(poll)
            wake.clear()
