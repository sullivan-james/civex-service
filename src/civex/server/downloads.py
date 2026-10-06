"""Disk-backed downloads for exports.

An export is built into a temp file while the request's DB session is still
open, then served from disk and deleted -- so its size is bounded by disk, not
memory, and no generator has to touch the session after the request's
dependencies have closed it.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


def new_temp_path(suffix: str = "") -> Path:
    fd, name = tempfile.mkstemp(prefix="civex-export-", suffix=suffix)
    os.close(fd)
    return Path(name)


def new_temp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="civex-export-"))


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


@contextmanager
def temp_paths() -> Iterator[list[Path]]:
    """Temp files (or folders) that are removed on exit unless handed to
    `serve()`."""
    paths: list[Path] = []
    try:
        yield paths
    finally:
        for p in paths:
            _remove(p)


def serve(path: Path, media_type: str, filename: str, *cleanup: Path) -> FileResponse:
    """Stream `path` as an attachment, deleting it (and `cleanup`) once sent."""
    doomed = (path, *cleanup)

    def _cleanup() -> None:
        for p in doomed:
            _remove(p)

    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        background=BackgroundTask(_cleanup),
    )
