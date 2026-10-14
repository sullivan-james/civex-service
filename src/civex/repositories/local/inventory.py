"""The inventory of copies: `stored_objects`, one row per (file, volume).

Every object store keeps what it holds here, whoever holds the bytes (a drive
on this machine, a bucket), so where a file is and how big it is are answered
from one table. These are the writes and reads the stores and repositories
share; each store's own business (walking a drive, listing a bucket) stays in
the store. A query asking whether a file is *here*, or how big it is, wants one
row per file, not one per copy, so it joins `stored_files()`, never the table.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select

from civex.db.models import StoredObject

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# How many ids an IN (...) carries at once.
CHUNK = 500


def stored_files() -> Any:
    """One row per file stored on some drive here: `sha`, `size`."""
    return (
        select(
            StoredObject.sha256.label("sha"),
            func.max(StoredObject.size).label("size"),
        )
        .group_by(StoredObject.sha256)
        .subquery("stored_files")
    )


def upsert_copies(
    session: Session, rows: list[tuple[str, str, int]], *, verified: bool
) -> None:
    """Record these copies (sha256, volume, size), updating the size of ones
    already recorded. `verified`: the bytes were hashed on the way in, so the
    copy is known to match; otherwise it waits for a read-back
    (`ObjectStore.verify`), and a copy already verified stays so. Records
    waiting for one of these files (cited before a copy was here, such as one
    another device added) are pointed at the copy just recorded."""
    from sqlalchemy import Table, update
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from civex.db.models import FileReference

    if not rows:
        return
    insert = (
        pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    )
    table = cast(Table, StoredObject.__table__)
    now = datetime.now(timezone.utc)
    stmt = insert(table).values(
        [
            {
                "sha256": sha,
                "volume": vol,
                "size": size,
                "created_at": now,
                "verified_at": now if verified else None,
            }
            for sha, vol, size in rows
        ]
    )
    changes: dict[str, Any] = {"size": stmt.excluded.size}
    if verified:
        changes["verified_at"] = now
    stmt = stmt.on_conflict_do_update(index_elements=["sha256", "volume"], set_=changes)
    session.execute(stmt)

    by_volume: dict[str, list[str]] = {}
    for sha, vol, _ in rows:
        by_volume.setdefault(vol, []).append(sha)
    for vol, shas in by_volume.items():
        for i in range(0, len(shas), CHUNK):
            session.execute(
                update(FileReference)
                .where(
                    FileReference.sha256.in_(shas[i : i + CHUNK]),
                    FileReference.volume.is_(None),
                )
                .values(volume=vol)
            )


def forget_copy(session: Session, sha256: str, volume: str | None = None) -> None:
    """Forget the copy on `volume`, or every copy. Records that pointed at a
    copy that is gone point at the newest copy left, or at none."""
    from sqlalchemy import delete, update

    from civex.db.models import FileReference

    query = delete(StoredObject).where(StoredObject.sha256 == sha256)
    if volume is not None:
        query = query.where(StoredObject.volume == volume)
    session.execute(query)
    left = (
        select(StoredObject.volume)
        .where(StoredObject.sha256 == sha256)
        .order_by(StoredObject.created_at.desc(), StoredObject.volume)
        .limit(1)
        .scalar_subquery()
    )
    pointing = update(FileReference).where(FileReference.sha256 == sha256)
    if volume is not None:
        pointing = pointing.where(FileReference.volume == volume)
    session.execute(pointing.values(volume=left))


def copies(
    session: Session, shas: Iterable[str], volumes: Iterable[str]
) -> dict[str, list[tuple[str, int]]]:
    """Every recorded copy of each file, as (volume, size), on the `volumes`
    named (in that order). A file with no copy is absent."""
    wanted = list(dict.fromkeys(shas))
    order = {name: i for i, name in enumerate(volumes)}
    out: dict[str, list[tuple[str, int]]] = {}
    if not wanted or not order:
        return out
    for i in range(0, len(wanted), CHUNK):
        rows = session.execute(
            select(StoredObject.sha256, StoredObject.volume, StoredObject.size).where(
                StoredObject.sha256.in_(wanted[i : i + CHUNK])
            )
        )
        for sha, volume, size in rows:
            if volume in order:
                out.setdefault(sha, []).append((volume, int(size)))
    for found in out.values():
        found.sort(key=lambda row: order[row[0]])
    return out


def copies_used(
    session: Session, record_ids: Iterable[uuid.UUID], volumes: Iterable[str]
) -> dict[tuple[uuid.UUID, str], str]:
    """(record, file) -> the volume of the copy that record uses, for records
    pointing at one on the `volumes` named."""
    from civex.db.models import FileReference

    wanted = list(dict.fromkeys(record_ids))
    known = set(volumes)
    out: dict[tuple[uuid.UUID, str], str] = {}
    if not wanted or not known:
        return out
    for i in range(0, len(wanted), CHUNK):
        for record_id, sha, volume in session.execute(
            select(
                FileReference.record_id, FileReference.sha256, FileReference.volume
            ).where(
                FileReference.record_id.in_(wanted[i : i + CHUNK]),
                FileReference.volume.is_not(None),
            )
        ):
            if volume in known and record_id is not None:
                out[(record_id, sha)] = volume
    return out


def unverified(session: Session, volume: str, after: str, limit: int) -> list[str]:
    """Files on `volume` whose copy hasn't been checked against its hash yet,
    in sha256 order from `after`."""
    return list(
        session.execute(
            select(StoredObject.sha256)
            .where(
                StoredObject.volume == volume,
                StoredObject.verified_at.is_(None),
                StoredObject.sha256 > after,
            )
            .order_by(StoredObject.sha256)
            .limit(limit)
        ).scalars()
    )


def mark_verified(session: Session, volume: str, shas: list[str]) -> None:
    from sqlalchemy import update

    now = datetime.now(timezone.utc)
    for i in range(0, len(shas), CHUNK):
        session.execute(
            update(StoredObject)
            .where(
                StoredObject.volume == volume,
                StoredObject.sha256.in_(shas[i : i + CHUNK]),
            )
            .values(verified_at=now)
        )


def remove_absent(session: Session, volume: str, present: set[str], batch: int) -> int:
    """Drop the rows of `volume` whose file is not in `present` (what a
    listing of the place just found), paging by sha256. Returns how many."""
    from sqlalchemy import delete

    removed = 0
    last = ""
    while True:
        rows = list(
            session.execute(
                select(StoredObject.sha256)
                .where(StoredObject.volume == volume, StoredObject.sha256 > last)
                .order_by(StoredObject.sha256)
                .limit(batch)
            ).scalars()
        )
        if not rows:
            return removed
        gone = [sha for sha in rows if sha not in present]
        if gone:
            session.execute(
                delete(StoredObject).where(
                    StoredObject.volume == volume, StoredObject.sha256.in_(gone)
                )
            )
            removed += len(gone)
        last = rows[-1]


def held(session: Session) -> dict[str, tuple[int, int]]:
    """Files and bytes recorded on each volume (a drive's name, or the bucket's
    `S3_VOLUME`): what a project would leave behind if it stopped using one."""
    rows = session.execute(
        select(
            StoredObject.volume,
            func.count(),
            func.coalesce(func.sum(StoredObject.size), 0),
        ).group_by(StoredObject.volume)
    ).all()
    return {str(volume): (int(files), int(size)) for volume, files, size in rows}
