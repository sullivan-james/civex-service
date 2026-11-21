"""The server's host for database upkeep: one thread that keeps the field
indexes in step (`IndexService.reconcile`) and refreshes the query planner's
statistics now and then (`db/statistics.py` decides what that does).

It reconciles when the server starts, when asked (`request()`: a field marked
indexed, **Rebuild now**), and when a check every `CHECK_SECONDS` finds the
database out of step with what is wanted (a uniqueness key added, a field or
schema deleted, by the app or by the CLI in another process): the check is
the schemas and the database's list of indexes, so it costs next to nothing.
Building an index on a big table takes a while and, on SQLite, holds the
database meanwhile, so it happens here and never in a request."""

from __future__ import annotations

import logging
import threading
import time

from civex.context import ContextFactory, local_context
from civex.domain.field_index import ReconcileResult

log = logging.getLogger(__name__)

CHECK_SECONDS = 60.0
STATISTICS_SECONDS = 600.0


class IndexJobs:
    def __init__(self, make_context: ContextFactory = local_context) -> None:
        self._make_context = make_context
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.building = False  # reconciling now
        self.last: ReconcileResult | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def ensure_running(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="index-upkeep"
            )
            self._thread.start()

    def request(self) -> None:
        """Reconcile soon (starting the thread if it isn't running)."""
        self._wake.set()
        self.ensure_running()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(2.0)

    def _run(self) -> None:
        last_statistics = time.monotonic()
        force = True
        while not self._stop.is_set():
            try:
                self._tick(force, time.monotonic() - last_statistics)
            except Exception as e:  # noqa: BLE001 - said in the app; tried again
                log.warning("index upkeep failed: %s", e)
                self.error = str(e)
            if time.monotonic() - last_statistics >= STATISTICS_SECONDS:
                last_statistics = time.monotonic()
            self._wake.wait(CHECK_SECONDS)
            force = self._wake.is_set()
            self._wake.clear()

    def _tick(self, force: bool, since_statistics: float) -> None:
        try:
            ctx = self._make_context()
        except Exception as e:  # noqa: BLE001 - no project (yet): nothing to keep
            log.debug("index upkeep skipped: %s", e)
            return
        try:
            if force or not ctx.index_svc.in_step():
                self.building = True
                result = ctx.index_svc.reconcile()
                ctx.commit()
                self.last, self.error = result, None
                if result.created or result.dropped:
                    log.info(
                        "field indexes: %d built, %d dropped in %.1fs",
                        len(result.created),
                        len(result.dropped),
                        result.seconds,
                    )
            if since_statistics >= STATISTICS_SECONDS:
                ctx.index_svc.refresh_statistics()
                ctx.commit()
        finally:
            self.building = False
            ctx.close()


index_jobs = IndexJobs()
