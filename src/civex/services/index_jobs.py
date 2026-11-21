"""Keeping the field indexes in step, always in the background.

`IndexService.reconcile` builds and drops indexes; this module is *where* it
runs, which is never inside a request or a command a person is waiting on:

- In the server, one thread (`index_jobs`): when the server starts, when asked
  (`request()`: a field marked indexed, a uniqueness key changed, a database
  moved), whenever a check every `CHECK_SECONDS` finds the database out of step
  (the CLI in another process changed something), and to refresh the query
  planner's statistics every `STATISTICS_SECONDS`.
- From the CLI, `queue_upkeep` after a command changed what is wanted: the
  server's thread if this process has one, else a process of its own
  (`civex db indexes --reconcile --background`), so the command returns at
  once. `civex db indexes --reconcile` is the one way to do it in the
  foreground, with a progress bar.

`run_upkeep` is the one way any of them does it: under the project's
`index-upkeep.lock` (one process at a time; another finds it busy and leaves
it, since the holder goes on until the database is in step), with progress for
the status bar. On SQLite a build gives way to saves (`db/index_gate.py`).
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

from civex.context import AppContext, ContextFactory, local_context
from civex.domain.field_index import IndexProgress, ReconcileResult
from civex.pid_lock import LockBusy, held, pid_lock
from civex.processes import new_group_kwargs

log = logging.getLogger(__name__)

CHECK_SECONDS = 60.0
STATISTICS_SECONDS = 600.0
LOCK = "index-upkeep.lock"
ROUNDS = 3  # reconciles in a row before leaving it to the next check


def _lock_path(ctx: AppContext) -> Path:
    return ctx.config.civex_dir / LOCK


def upkeep_running(ctx: AppContext) -> bool:
    """Whether some process is keeping this project's indexes now."""
    return held(_lock_path(ctx))


def run_upkeep(
    ctx: AppContext,
    progress: Callable[[IndexProgress], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ReconcileResult | None:
    """Bring the indexes in step, again while something changed meanwhile.
    None when another process is already doing it."""
    with ExitStack() as stack:
        try:
            stack.enter_context(pid_lock(_lock_path(ctx)))
        except LockBusy:
            return None
        total = ReconcileResult()
        for _ in range(ROUNDS):
            if ctx.index_svc.in_step():
                break
            result = ctx.index_svc.reconcile(progress, should_stop)
            total.created += result.created
            total.dropped += result.dropped
            total.yielded += result.yielded
            total.seconds += result.seconds
            if result.stopped:
                total.stopped = True
                break
        return total


def start_background_upkeep(project_root: Path, civex_dir: Path) -> None:
    """Start a process of its own that keeps the indexes and exits (the CLI's
    way: the command that asked returns at once). Its output goes to
    `_civex/logs/index-upkeep.log`."""
    logs = civex_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = open(logs / "index-upkeep.log", "a", encoding="utf-8")  # noqa: SIM115
    try:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "civex.main",
                "db",
                "indexes",
                "--reconcile",
                "--background",
            ],
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **new_group_kwargs(),
        )
    finally:
        out.close()


QUEUED_HERE = "here"  # this process's thread will do it
QUEUED_ELSEWHERE = "elsewhere"  # another process is doing it
QUEUED_STARTED = "started"  # a process of its own was started
IN_STEP = "in_step"  # nothing to do


def queue_upkeep(ctx: AppContext) -> str:
    """Have the indexes brought in step in the background, after something
    changed what is wanted. Call after committing. Says who will do it."""
    if ctx.index_svc.in_step():
        return IN_STEP
    if index_jobs.running:
        index_jobs.request()
        return QUEUED_HERE
    if upkeep_running(ctx):
        return QUEUED_ELSEWHERE
    start_background_upkeep(ctx.config.project_root, ctx.config.civex_dir)
    return QUEUED_STARTED


class IndexJobs:
    def __init__(self, make_context: ContextFactory = local_context) -> None:
        self._make_context = make_context
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.progress: IndexProgress | None = None  # while building or waiting
        self.last: ReconcileResult | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def building(self) -> bool:
        return self.progress is not None

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

    def _show(self, progress: IndexProgress) -> None:
        self.progress = progress

    def _tick(self, force: bool, since_statistics: float) -> None:
        try:
            ctx = self._make_context()
        except Exception as e:  # noqa: BLE001 - no project (yet): nothing to keep
            log.debug("index upkeep skipped: %s", e)
            return
        try:
            if force or not ctx.index_svc.in_step():
                result = run_upkeep(ctx, self._show, self._stop.is_set)
                if result is not None:
                    self.last, self.error = result, None
                    if result.created or result.dropped:
                        log.info(
                            "field indexes: %d built, %d dropped in %.1fs "
                            "(gave way to saves %d times)",
                            len(result.created),
                            len(result.dropped),
                            result.seconds,
                            result.yielded,
                        )
            if since_statistics >= STATISTICS_SECONDS:
                ctx.index_svc.refresh_statistics()
                ctx.commit()
        finally:
            self.progress = None
            ctx.close()


index_jobs = IndexJobs()
