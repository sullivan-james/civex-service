"""Disk-backed downloads for exports.

An export is built into a temp file while the request's DB session is still
open, then served from disk and deleted -- so its size is bounded by disk, not
memory, and no generator has to touch the session after the request's
dependencies have closed it.
"""

from __future__ import annotations

import os
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


@contextmanager
def temp_paths() -> Iterator[list[Path]]:
    """Temp files that are removed on exit unless handed to `serve()`."""
    paths: list[Path] = []
    try:
        yield paths
    finally:
        for p in paths:
            p.unlink(missing_ok=True)


def serve(path: Path, media_type: str, filename: str, *cleanup: Path) -> FileResponse:
    """Stream `path` as an attachment, deleting it (and `cleanup`) once sent."""
    doomed = (path, *cleanup)

    def _cleanup() -> None:
        for p in doomed:
            p.unlink(missing_ok=True)

    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        background=BackgroundTask(_cleanup),
    )
