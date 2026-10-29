"""Plugin processes kept running between steps.

Starting a plugin is most of what a small step costs: `uv` finds the script's
environment, a Python starts and imports pydantic and the SDK. The SDK's
`serve_loop` answers any number of `describe` and `run` requests, so a process
that answered one is kept here and handed the next request for the same
plugin instead of starting another.

A worker is keyed by what it was started from (the plugin's path, a hash of
its contents and the command line), so an edited plugin, or one run with a
different SDK pin, gets a new process and the old one is left to expire. A
worker is used by one step at a time; two runs of the same plugin at once each
get their own. One that broke (timed out, died, spoke out of turn) is stopped
rather than kept. Idle workers are stopped after `IDLE_SECONDS`, and every
worker when the process exits (`atexit`) or the server shuts down.

A plugin's module-level state therefore lives from one run to the next, as in
any long-lived server. Its working folder is emptied before each run.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from pathlib import Path

#: How long a worker nobody has used is kept before it is stopped.
IDLE_SECONDS = 300.0
#: Idle workers kept per plugin; more only appear when runs overlap.
MAX_IDLE_PER_KEY = 2


@dataclass(eq=False)
class Worker:
    """One plugin process and the folder it runs in."""

    key: Hashable
    proc: subprocess.Popen
    scratch_dir: Path
    stop: Callable[["Worker"], None]
    idle_since: float = field(default=0.0)
    #: Requests it finished and was kept after.
    runs: int = 0

    def alive(self) -> bool:
        return self.proc.poll() is None

    def empty_scratch(self) -> None:
        """Remove what an earlier run left in the folder (the folder stays:
        it is the process's working directory)."""
        if not self.scratch_dir.is_dir():
            self.scratch_dir.mkdir(parents=True, exist_ok=True)
            return
        for child in self.scratch_dir.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    def close(self) -> None:
        try:
            self.stop(self)
        finally:
            shutil.rmtree(self.scratch_dir, ignore_errors=True)


class WorkerPool:
    """Idle workers by key, a lock around them, and a thread that stops the
    ones idle too long."""

    def __init__(
        self,
        idle_seconds: float = IDLE_SECONDS,
        max_idle_per_key: int = MAX_IDLE_PER_KEY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.idle_seconds = idle_seconds
        self.max_idle_per_key = max_idle_per_key
        self._clock = clock
        self._idle: dict[Hashable, list[Worker]] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._reaper: threading.Thread | None = None

    def checkout(self, key: Hashable, start: Callable[[], Worker]) -> Worker:
        """An idle worker for `key`, or a new one from `start()`. Its folder
        is empty either way."""
        stale: list[Worker] = []
        worker: Worker | None = None
        with self._lock:
            waiting = self._idle.get(key, [])
            while waiting:
                candidate = waiting.pop()
                if candidate.alive():
                    worker = candidate
                    break
                stale.append(candidate)
            if not waiting:
                self._idle.pop(key, None)
        for dead in stale:
            dead.close()
        if worker is None:
            return start()
        worker.empty_scratch()
        return worker

    def checkin(self, worker: Worker, healthy: bool) -> None:
        """Keep `worker` for the next request if it is `healthy` and still
        running and there is room; otherwise stop it."""
        keep = healthy and self.idle_seconds > 0 and worker.alive()
        if keep:
            with self._lock:
                waiting = self._idle.setdefault(worker.key, [])
                if len(waiting) < self.max_idle_per_key:
                    worker.runs += 1
                    worker.idle_since = self._clock()
                    waiting.append(worker)
                    self._ensure_reaper()
                    return
        worker.close()

    def reap(self) -> int:
        """Stop the workers idle longer than `idle_seconds`; how many."""
        now = self._clock()
        expired: list[Worker] = []
        with self._lock:
            for key in list(self._idle):
                keep = []
                for worker in self._idle[key]:
                    if now - worker.idle_since >= self.idle_seconds:
                        expired.append(worker)
                    else:
                        keep.append(worker)
                if keep:
                    self._idle[key] = keep
                else:
                    del self._idle[key]
        for worker in expired:
            worker.close()
        return len(expired)

    def idle_count(self) -> int:
        with self._lock:
            return sum(len(w) for w in self._idle.values())

    def close(self) -> None:
        """Stop every idle worker (and the reaper)."""
        with self._lock:
            workers = [w for waiting in self._idle.values() for w in waiting]
            self._idle.clear()
            reaper, self._reaper = self._reaper, None
        self._wake.set()
        for worker in workers:
            worker.close()
        if reaper is not None:
            reaper.join(timeout=1.0)
        self._wake.clear()

    def _ensure_reaper(self) -> None:
        # Called with the lock held.
        if self._reaper is not None and self._reaper.is_alive():
            return
        interval = max(1.0, min(self.idle_seconds / 4, 30.0))

        def loop() -> None:
            while not self._wake.wait(interval):
                self.reap()
                if self.idle_count() == 0:
                    with self._lock:
                        if not self._idle:
                            self._reaper = None
                            return

        self._reaper = threading.Thread(
            target=loop, name="civex-plugin-reaper", daemon=True
        )
        self._reaper.start()


#: The process's one pool, shared by every project it opens (keys are full
#: paths, so two projects' plugins never share a worker).
POOL = WorkerPool()
atexit.register(POOL.close)
