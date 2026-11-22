"""One sync at a time per project, across processes.

The server's background sync, `civex sync` in a terminal and a second window
would otherwise push the same changes at once. The lock is a file owned by a
process id (`civex/pid_lock.py`): one held by a process that has died, or left
over for over an hour, is free (a crash must never leave sync stuck).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from civex.pid_lock import LockBusy, held, pid_lock


class SyncBusy(RuntimeError):
    """Another sync is already running for this project."""


@contextmanager
def sync_lock(civex_dir: Path) -> Iterator[None]:
    with ExitStack() as stack:
        try:
            stack.enter_context(pid_lock(civex_dir / "sync.lock"))
        except LockBusy:
            raise SyncBusy("Another sync is already running") from None
        yield


def sync_running(civex_dir: Path) -> bool:
    return held(civex_dir / "sync.lock")
