"""The server's host for background sync: one thread running a SyncWorker, the
handle the API uses to ask it to sync now, and connecting to an authority, which
can take a long time (copying a project), on a thread of its own.

How far a long step has got is kept here, in memory, for the app to show: it is
a notice about work going on in this process, not state anyone needs after a
restart (an interrupted copy is simply begun again)."""

from __future__ import annotations

import logging
import threading

from civex.config import load_config
from civex.context import build_local_context
from civex.domain.sync import SyncProgress
from civex.services.sync_worker import SyncWorker

log = logging.getLogger(__name__)


class SyncJobs:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connecting: threading.Thread | None = None
        # The copy started by `start_connect`, while it runs.
        self.copy_progress: SyncProgress | None = None
        # The history from before joining, while the worker fetches it.
        self.history_progress: SyncProgress | None = None
        # Why the last connect that ran here failed, until another starts.
        self.connect_error: str | None = None
        self.worker = SyncWorker(
            load_config, build_local_context, on_progress=self._history
        )

    @property
    def progress(self) -> SyncProgress | None:
        """What to show: a copy going on first, else history arriving."""
        return self.copy_progress or self.history_progress

    @property
    def connecting(self) -> bool:
        thread = self._connecting
        return thread is not None and thread.is_alive()

    def _history(self, progress: SyncProgress | None) -> None:
        self.history_progress = progress

    def ensure_worker(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self.worker.run,
                args=(self._stop,),
                daemon=True,
                name="sync-worker",
            )
            self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(2.0)

    def fetch_now(self, total: int) -> None:
        """Start downloading what this computer keeps (a collection was just
        set to keep its files here): the progress is there at once, before the
        worker has started, so the status bar shows it on the next read."""
        self.ensure_worker()
        self.worker.request_files(total)

    def sync_now(self) -> None:
        self.ensure_worker()
        self.worker.request()

    def start_connect(self, url: str) -> None:
        """Connect to an authority on a thread of its own (already checked, and
        joined with any invite, by `SyncService.check_connect`), saying how far
        it has got as it goes, then start syncing in the background."""
        with self._lock:
            if self.connecting:
                return
            self.connect_error = None
            self.copy_progress = None
            self._connecting = threading.Thread(
                target=self._connect,
                args=(url,),
                daemon=True,
                name="sync-connect",
            )
            self._connecting.start()

    def _connect(self, url: str) -> None:
        ctx = build_local_context(load_config())
        try:
            ctx.sync_svc.connect(url, None, progress=self._copied)
            ctx.commit()
        except Exception as e:  # noqa: BLE001 - said in the app, not lost
            log.warning("connecting to %s failed: %s", url, e)
            self.connect_error = str(e) or type(e).__name__
            return
        finally:
            ctx.close()
            self.copy_progress = None
        self.sync_now()

    def _copied(self, progress: SyncProgress) -> None:
        self.copy_progress = progress


sync_jobs = SyncJobs()
