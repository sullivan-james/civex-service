"""One sync at a time per project, across processes.

The server's background sync, `civex sync` in a terminal and a second window
would otherwise push the same changes at once. The lock is a file owned by a
process id (`civex/pid_lock.py`): one held by a process that has died, or left
over for over an hour, is free (a crash must never leave sync stuck).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from civex.pid_lock import LockBusy, held, pid_lock


class SyncBusy(RuntimeError):
    """Another sync is already running for this project."""


@contextmanager
def sync_lock(civex_dir: Path, wait: float = 0.0) -> Iterator[None]:
    """Hold the project's sync lock, waiting up to `wait` seconds for another
    sync to finish; `SyncBusy` when it is still running after that."""
    deadline = time.monotonic() + wait
    with ExitStack() as stack:
        while True:
            try:
                stack.enter_context(pid_lock(civex_dir / "sync.lock"))
                break
            except LockBusy:
                if time.monotonic() >= deadline:
                    raise SyncBusy(
                        "Another sync is already running for this project; "
                        "this one was skipped."
                    ) from None
                time.sleep(0.25)
        yield


def sync_running(civex_dir: Path) -> bool:
    return held(civex_dir / "sync.lock")
