"""Building zip archives of stored files without holding any of them in memory."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from civex.domain import tables
from civex.domain.dtos import FileRef
from civex.domain.exceptions import ValidationError
from civex.domain.file_access import FilePlan, FileSelection
from civex.services.file_access_service import MISSING_NOTE, FileAccessService
from civex.services.file_service import FileService


def write_zip(
    dest: Path,
    file_svc: FileService,
    entries: Iterable[tuple[str, FileRef]],
    data_member: tuple[str, Path] | None = None,
    extra_members: Iterable[tuple[str, Path]] = (),
) -> None:
    """Write `entries` (archive name, blob) to `dest`, preceded by an optional
    local file (e.g. the CSV an export was written to) and any `extra_members`
    (archive name, local file; e.g. a MISSING.txt). Each blob is copied
    from its on-disk object by `zipfile`, which streams in fixed-size chunks
    -- unlike `zf.writestr(name, file_svc.retrieve(...))`, peak memory is
    independent of file size. Raises FileNotFoundError for a blob that is not
    stored locally; the caller owns cleanup of `dest`."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        if data_member is not None:
            name, path = data_member
            zf.write(path, arcname=name)
        for name, path in extra_members:
            zf.write(path, arcname=name)
        for name, ref in entries:
            zf.write(file_svc.local_path(ref.sha256), arcname=name)


@dataclass
class Download:
    """What a person is handed: a file made in the scratch folder, and the name
    and type to give it."""

    path: Path
    filename: str
    media_type: str


def build_download(
    access: FileAccessService,
    file_svc: FileService,
    selection: FileSelection,
    plan: FilePlan,
    scratch: Path,
    name: str | None = None,
    dest: Path | None = None,
) -> Download:
    """The selection as one thing to hand over, with the same paths and the same
    tables as a folder export: a zip of the files, their tables and (if some
    couldn't be reached) a MISSING.txt, or -- when the selection is one table and
    nothing else -- just that table. Built in `scratch`, or at `dest` when given.
    Raises FileNotFoundError for a blob that is not stored locally."""
    made = access.write_tables(selection, plan, scratch)
    entries = access.zip_entries(plan)
    note = access.missing_note(plan)
    if not entries and not note and not made:
        raise ValidationError("There is nothing to export.")
    if not entries and not note and len(made) == 1:
        path = made[0][1]
        planned = plan.tables[0]
        fmt = planned.format
        filename = planned.name
        if name:
            filename = name + tables.extension(fmt)
        if dest is not None:
            path.replace(dest)
            path = dest
        return Download(path, filename, tables.media_type(fmt))
    extra = list(made)
    if note:
        note_path = scratch / MISSING_NOTE
        note_path.write_text(note, "utf-8")
        extra.append((MISSING_NOTE, note_path))
    target = dest or scratch / "export.zip"
    try:
        write_zip(target, file_svc, entries, extra_members=extra)
    except FileNotFoundError:
        target.unlink(missing_ok=True)
        raise
    return Download(target, f"{name or 'files'}.zip", "application/zip")
