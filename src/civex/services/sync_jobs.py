"""The server's host for background sync: one thread running a SyncWorker, and
the handle the API uses to ask it to sync now."""

from __future__ import annotations

import threading

from civex.config import load_config
from civex.context import build_local_context
from civex.services.sync_worker import SyncWorker


class SyncJobs:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.worker = SyncWorker(load_config, build_local_context)

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

    def sync_now(self) -> None:
        self.ensure_worker()
        self.worker.request()


sync_jobs = SyncJobs()
