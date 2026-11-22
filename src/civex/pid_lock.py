"""A lock across processes: a file holding the owner's process id, made with
O_EXCL. One held by a process that has died is free at once, and one with no
readable owner after `STALE_SECONDS` (a crash must never leave work stuck)."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from civex.processes import pid_alive

STALE_SECONDS = 3600


class LockBusy(RuntimeError):
    """Another live process holds the lock."""


def _owner(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def held(path: Path) -> bool:
    """Whether a live process holds the lock at `path`."""
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
def pid_lock(path: Path) -> Iterator[None]:
    """Hold the lock at `path`, or raise `LockBusy`."""
    if held(path):
        raise LockBusy(str(path))
    path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        raise LockBusy(str(path))
    try:
        os.write(fd, str(os.getpid()).encode())
    finally:
        os.close(fd)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
