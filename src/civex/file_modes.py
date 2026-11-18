"""Stored files that are protected from edits, and that civex can still remove.

A folder an export opens holds hard links: each is the stored file itself under
another name, so saving over one would change the project's own copy and leave
it no longer matching its hash. `make_read_only` takes the write permission off
such a file (on Windows, its read-only attribute), so a program says it can't
save instead of quietly damaging the store. Being one file, the stored copy is
read-only too, which nothing in civex minds: stored files are only ever written
whole to a scratch file and renamed into place, and removed.

POSIX lets a read-only file be removed or replaced (that is the folder's
permission, not the file's); Windows does not. `remove` and `replace` are how the
store and the exports remove or replace a file that may be read-only, on either.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

_WRITE = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def make_read_only(path: Path | str) -> None:
    """Take every write permission off `path`. Best effort: a file this user
    can't change the mode of (another owner, a drive that keeps no modes) is left
    as it is."""
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, stat.S_IMODE(mode) & ~_WRITE)
    except OSError:
        pass


def _writable(path: Path | str) -> bool:
    """Give the owner write permission back, so Windows lets it go. False when
    that can't be done (it isn't there, or isn't ours)."""
    try:
        os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) | stat.S_IWUSR)
        return True
    except OSError:
        return False


def remove(path: Path | str, missing_ok: bool = False) -> None:
    """Remove a file, even one marked read-only."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        if not missing_ok:
            raise
    except PermissionError:
        if not _writable(path):
            raise
        os.unlink(path)


def replace(source: Path | str, target: Path | str) -> None:
    """`os.replace`, even when the file being replaced is marked read-only."""
    try:
        os.replace(source, target)
    except PermissionError:
        if not _writable(target):
            raise
        os.replace(source, target)
