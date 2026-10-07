from __future__ import annotations

import uuid
from typing import Any, Iterable

from sqlalchemy import case, delete, func, insert, null, select
from sqlalchemy.orm import Session

from civex.db.models import FileReference, Record, WorkflowJob
from civex.domain.file_refs import collect_sha256_refs

_BATCH = 1000


class LocalFileReferenceRepository:
    """Read side of `file_references` (maintained by ORM events in
    civex.db.models) plus a from-scratch rebuild for when it's in doubt."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def referenced_subset(self, shas: Iterable[str]) -> set[str]:
        """Which of `shas` are referenced by at least one live owner -- a
        single indexed lookup, so GC can check a batch of blobs without
        loading any record or job."""
        wanted = list(shas)
        if not wanted:
            return set()
        rows = self._s.execute(
            select(FileReference.sha256)
            .where(FileReference.sha256.in_(wanted))
            .distinct()
        )
        return {sha for (sha,) in rows}

    def usage(self, sha256: str) -> tuple[dict[uuid.UUID | None, int], int]:
        """What uses a blob: the number of records that reference it in each
        collection, and the number of workflow runs that took it as input."""
        by_collection = {
            dataset_id: n
            for dataset_id, n in self._s.execute(
                select(
                    Record.dataset_id,
                    func.count(func.distinct(FileReference.record_id)),
                )
                .join(Record, Record.id == FileReference.record_id)
                .where(FileReference.sha256 == sha256)
                .group_by(Record.dataset_id)
            )
        }
        jobs = self._s.execute(
            select(func.count(func.distinct(FileReference.job_id))).where(
                FileReference.sha256 == sha256, FileReference.job_id.is_not(None)
            )
        ).scalar_one()
        return by_collection, int(jobs)

    def shas_for_collections(
        self, collection_ids: list[str], after: str | None, limit: int
    ) -> list[str]:
        """The distinct files records in these collections use, in hash order,
        `limit` at a time starting after `after` (keyset paging, so memory stays
        flat however many files there are)."""
        ids = [uuid.UUID(c) for c in collection_ids]
        query = (
            select(FileReference.sha256)
            .join(Record, Record.id == FileReference.record_id)
            # Live records: a deleted record's files are left where they are
            # (moving a drive's contents still takes them).
            .where(Record.dataset_id.in_(ids), Record.deleted_at.is_(None))
            .distinct()
            .order_by(FileReference.sha256)
            .limit(limit)
        )
        if after is not None:
            query = query.where(FileReference.sha256 > after)
        return [sha for (sha,) in self._s.execute(query)]

    def surplus_by_volume(self) -> dict[str, tuple[int, int, int, int]]:
        """Per volume, the catalog's files that no collection uses, in one query:
        (unused files, unused bytes, history-only files, history-only bytes).
        "Unused" has no owner at all; "history-only" is kept only because a
        workflow run took it as an input."""
        from civex.db.models import StoredObject

        def has(column: Any) -> Any:
            return (
                select(FileReference.id)
                .where(FileReference.sha256 == StoredObject.sha256)
                .where(column.is_not(None))
                .exists()
            )

        by_record, by_job = has(FileReference.record_id), has(FileReference.job_id)
        unused, history = ~by_record & ~by_job, ~by_record & by_job
        rows = self._s.execute(
            select(
                StoredObject.volume,
                func.coalesce(func.sum(case((unused, 1), else_=0)), 0),
                func.coalesce(func.sum(case((unused, StoredObject.size), else_=0)), 0),
                func.coalesce(func.sum(case((history, 1), else_=0)), 0),
                func.coalesce(func.sum(case((history, StoredObject.size), else_=0)), 0),
            ).group_by(StoredObject.volume)
        )
        return {v: (int(a), int(b), int(c), int(d)) for v, a, b, c, d in rows}

    def volume_breakdowns(
        self, collection_ids: list[str] | None, homes: dict[str, str] | None = None
    ) -> dict[str, tuple[int, list[tuple[str, int, int, int]]]]:
        """Where collections' files are, from the catalog in a few grouped
        queries (no file is read), for the given collections or all of them.
        Per collection id: the number of distinct files its records use, and per
        volume (volume, files, bytes, files another collection also uses). A
        file stored on several drives counts once, on the collection's home
        (`homes`: collection id -> drive) when a copy is there, else on the
        first drive by name that holds it."""
        from civex.db.models import StoredObject

        wanted = (
            None if collection_ids is None else [uuid.UUID(c) for c in collection_ids]
        )

        def scoped(query):
            return (
                query if wanted is None else query.where(Record.dataset_id.in_(wanted))
            )

        # one row per (collection, file), of its live records: what a person
        # sees as its files (a deleted record's are in Recently Deleted)
        mine = scoped(
            select(Record.dataset_id.label("cid"), FileReference.sha256.label("sha"))
            .join(Record, Record.id == FileReference.record_id)
            .where(Record.deleted_at.is_(None))
            .distinct()
        ).subquery()

        out: dict[str, tuple[int, list[tuple[str, int, int, int]]]] = {}
        for cid, n in self._s.execute(
            select(mine.c.cid, func.count()).group_by(mine.c.cid)
        ):
            out[str(cid)] = (int(n), [])

        # how many collections use each of those files, to spot shared ones
        users = (
            select(
                FileReference.sha256.label("sha"),
                func.count(func.distinct(Record.dataset_id)).label("n"),
            )
            .join(Record, Record.id == FileReference.record_id)
            .where(
                FileReference.sha256.in_(select(mine.c.sha)),
                Record.deleted_at.is_(None),
            )
            .group_by(FileReference.sha256)
            .subquery()
        )
        # each (collection, file) once, on the copy that counts for it
        home: Any = (
            case(
                {uuid.UUID(c): v for c, v in homes.items()},
                value=mine.c.cid,
                else_=None,
            )
            if homes
            else null()
        )
        counted = (
            select(
                mine.c.cid.label("cid"),
                mine.c.sha.label("sha"),
                func.coalesce(
                    func.max(case((StoredObject.volume == home, StoredObject.volume))),
                    func.min(StoredObject.volume),
                ).label("volume"),
                func.max(StoredObject.size).label("size"),
            )
            .join(StoredObject, StoredObject.sha256 == mine.c.sha)
            .group_by(mine.c.cid, mine.c.sha)
            .subquery()
        )
        rows = self._s.execute(
            select(
                counted.c.cid,
                counted.c.volume,
                func.count(),
                func.coalesce(func.sum(counted.c.size), 0),
                func.coalesce(func.sum(case((users.c.n > 1, 1), else_=0)), 0),
            )
            .join(users, users.c.sha == counted.c.sha)
            .group_by(counted.c.cid, counted.c.volume)
        )
        for cid, volume, files, size, shared in rows:
            out[str(cid)][1].append((volume, int(files), int(size), int(shared)))
        return out

    def records_using(self, shas: Iterable[str]) -> dict[str, set[uuid.UUID]]:
        """For each file, the live records that use it."""
        wanted = list(dict.fromkeys(shas))
        out: dict[str, set[uuid.UUID]] = {}
        for i in range(0, len(wanted), 500):
            for sha, record_id in self._s.execute(
                select(FileReference.sha256, FileReference.record_id)
                .join(Record, Record.id == FileReference.record_id)
                .where(
                    FileReference.sha256.in_(wanted[i : i + 500]),
                    Record.deleted_at.is_(None),
                )
            ):
                out.setdefault(sha, set()).add(record_id)
        return out

    def collections_using(self, shas: Iterable[str]) -> dict[str, set[str]]:
        """For each file, the ids of the collections whose records use it."""
        wanted = list(shas)
        out: dict[str, set[str]] = {}
        if not wanted:
            return out
        rows = self._s.execute(
            select(FileReference.sha256, Record.dataset_id)
            .join(Record, Record.id == FileReference.record_id)
            .where(FileReference.sha256.in_(wanted), Record.deleted_at.is_(None))
            .distinct()
        )
        for sha, dataset_id in rows:
            if dataset_id is not None:
                out.setdefault(sha, set()).add(str(dataset_id))
        return out

    def count_referenced(self) -> int:
        return self._s.execute(
            select(func.count(func.distinct(FileReference.sha256)))
        ).scalar_one()

    def rebuild(self) -> int:
        """Discard and recompute every reference row by scanning all records
        (soft-deleted ones included -- they're restorable) and all jobs'
        `input_data`, in keyset-paged batches so memory stays O(batch).
        The escape hatch for a table that may have drifted (raw SQL edits,
        an import that bypassed the ORM). Returns the number of rows."""
        self._s.execute(delete(FileReference))
        total = 0
        for model, col, owner in (
            (Record, Record.data, "record_id"),
            (WorkflowJob, WorkflowJob.input_data, "job_id"),
        ):
            last: uuid.UUID | None = None
            while True:
                q = select(model.id, col).order_by(model.id).limit(_BATCH)
                if last is not None:
                    q = q.where(model.id > last)
                rows = self._s.execute(q).all()
                if not rows:
                    break
                last = rows[-1][0]
                out = [
                    {
                        "id": uuid.uuid4(),
                        "sha256": sha,
                        "record_id": oid if owner == "record_id" else None,
                        "job_id": oid if owner == "job_id" else None,
                    }
                    for oid, payload in rows
                    for sha in collect_sha256_refs(payload)
                ]
                if out:
                    self._s.execute(insert(FileReference), out)
                    total += len(out)
        return total
