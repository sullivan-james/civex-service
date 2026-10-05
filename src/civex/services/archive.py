"""Building zip archives of stored files without holding any of them in memory."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterable

from civex.domain.dtos import FileRef
from civex.services.file_service import FileService


def write_zip(
    dest: Path,
    file_svc: FileService,
    entries: Iterable[tuple[str, FileRef]],
    data_member: tuple[str, Path] | None = None,
) -> None:
    """Write `entries` (archive name, blob) to `dest`, preceded by an optional
    local file (e.g. the CSV an export was written to). Each blob is copied
    from its on-disk object by `zipfile`, which streams in fixed-size chunks
    -- unlike `zf.writestr(name, file_svc.retrieve(...))`, peak memory is
    independent of file size. Raises FileNotFoundError for a blob that is not
    stored locally; the caller owns cleanup of `dest`."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        if data_member is not None:
            name, path = data_member
            zf.write(path, arcname=name)
        for name, ref in entries:
            zf.write(file_svc.local_path(ref.sha256), arcname=name)
