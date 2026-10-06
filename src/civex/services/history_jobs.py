"""The server's host for converting old history to deltas: one thread, started
when the server starts, that converts a batch, commits, pauses so the project
stays responsive, and stops when nothing is left. How far it has got is kept in
memory for the app to show (what is left is in the database, so a restart just
carries on)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from civex.config import load_config
from civex.context import build_local_context

log = logging.getLogger(__name__)

# Between batches: a write holds SQLite for its length, so short batches with a
# breath between them keep edits made meanwhile from waiting.
PAUSE_SECONDS = 0.2


@dataclass
class CompactionProgress:
    done: int  # entries looked at since it started
    total: int  # what was left when it started
    converted: int
    kept: int


class HistoryJobs:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.progress: CompactionProgress | None = None
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
                target=self._run, daemon=True, name="history-compaction"
            )
            self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(2.0)

    def _run(self) -> None:
        try:
            ctx = build_local_context(load_config())
        except Exception as e:  # noqa: BLE001 - no project to convert: nothing to do
            log.debug("history conversion not started: %s", e)
            return
        try:
            total = ctx.compaction_svc.remaining()
            if total == 0:
                return
            log.info("converting %d history entries to deltas", total)
            self.progress = CompactionProgress(0, total, 0, 0)
            while not self._stop.is_set():
                step = ctx.compaction_svc.step()
                ctx.commit()
                p = self.progress
                p.converted += step.converted
                p.kept += step.kept
                p.done = p.total - step.remaining
                if step.remaining == 0 or step.converted + step.kept == 0:
                    break
                self._stop.wait(PAUSE_SECONDS)
            log.info(
                "history conversion: %d converted, %d kept whole",
                self.progress.converted,
                self.progress.kept,
            )
        except Exception as e:  # noqa: BLE001 - said in the app; tried again next start
            log.warning("history conversion stopped: %s", e)
            self.error = str(e)
        finally:
            ctx.close()
            self.progress = None


history_jobs = HistoryJobs()
