"""One sync at a time per project, across processes.

The server's background sync, `civex sync` in a terminal and a second window
would otherwise push the same changes at once. The lock is a file owned by a
process id: one held by a process that has died, or left over for over an hour,
is free (a crash must never leave sync stuck).
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from civex.processes import pid_alive

STALE_SECONDS = 3600


class SyncBusy(RuntimeError):
    """Another sync is already running for this project."""


def _owner(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _live(path: Path) -> bool:
    if not path.exists():
        return False
    owner = _owner(path)
    if owner is not None:
        return pid_alive(owner)
    try:  # no readable owner: fall back to how old it is
        return time.time() - path.stat().st_mtime < STALE_SECONDS
    except OSError:
        return False


@contextmanager
def sync_lock(civex_dir: Path) -> Iterator[None]:
    path = civex_dir / "sync.lock"
    if _live(path):
        raise SyncBusy("Another sync is already running")
    path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        raise SyncBusy("Another sync is already running")
    try:
        os.write(fd, str(os.getpid()).encode())
    finally:
        os.close(fd)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def sync_running(civex_dir: Path) -> bool:
    return _live(civex_dir / "sync.lock")
