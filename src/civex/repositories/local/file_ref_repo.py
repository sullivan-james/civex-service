from __future__ import annotations

import uuid
from typing import Any, Iterable

from sqlalchemy import case, delete, func, insert, select, update
from sqlalchemy.orm import Session

from civex.db.models import FileReference, Record, WorkflowJob
from civex.domain.file_refs import collect_sha256_refs
from civex.domain.placement import Pointer

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

    def copies_in_use(self, copies: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
        """Which of these copies (sha256, volume) are in use: something points
        at the copy. Every copy of a file counts as in use when an owner of it
        points at no copy yet, when a workflow run uses it, or when none of the
        copies its owners point at is recorded here (so a missing copy can never
        make the one real one look unused). A copy of a file nothing uses is not
        in use. A query or two per 500 files."""
        from civex.db.models import StoredObject

        wanted = list(dict.fromkeys(copies))
        shas = list(dict.fromkeys(sha for sha, _ in wanted))
        pointed: dict[str, set[str]] = {}
        keep_all: set[str] = set()
        for i in range(0, len(shas), 500):
            chunk = shas[i : i + 500]
            for sha, volume, job_id in self._s.execute(
                select(
                    FileReference.sha256, FileReference.volume, FileReference.job_id
                ).where(FileReference.sha256.in_(chunk))
            ):
                pointed.setdefault(sha, set())
                if volume is None or job_id is not None:
                    keep_all.add(sha)
                else:
                    pointed[sha].add(volume)
            present: dict[str, set[str]] = {}
            for sha, volume in self._s.execute(
                select(StoredObject.sha256, StoredObject.volume).where(
                    StoredObject.sha256.in_(chunk)
                )
            ):
                present.setdefault(sha, set()).add(volume)
            for sha in chunk:
                if sha in pointed and not (pointed[sha] & present.get(sha, set())):
                    keep_all.add(sha)
        return {
            (sha, volume)
            for sha, volume in wanted
            if sha in keep_all or volume in pointed.get(sha, set())
        }

    def usage(self, sha256: str) -> tuple[dict[uuid.UUID | None, int], int, int]:
        """What uses a blob: the number of live records that reference it in
        each collection, the number of workflow runs that took it as input,
        and the number of deleted records that still reference it (they keep
        it while they can be restored, but don't count as using it)."""
        live = Record.deleted_at.is_(None)
        by_collection: dict[uuid.UUID | None, int] = {}
        deleted = 0
        for dataset_id, is_live, n in self._s.execute(
            select(
                Record.dataset_id,
                live,
                func.count(func.distinct(FileReference.record_id)),
            )
            .join(Record, Record.id == FileReference.record_id)
            .where(FileReference.sha256 == sha256)
            .group_by(Record.dataset_id, live)
        ):
            if is_live:
                by_collection[dataset_id] = int(n)
            else:
                deleted += int(n)
        jobs = self._s.execute(
            select(func.count(func.distinct(FileReference.job_id))).where(
                FileReference.sha256 == sha256, FileReference.job_id.is_not(None)
            )
        ).scalar_one()
        return by_collection, int(jobs), deleted

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

    def surplus_by_volume(self) -> dict[str, tuple[int, int, int, int, int, int]]:
        """Per volume, in one query: (unused files, unused bytes, history-only
        files, history-only bytes, shared files, shared bytes). "Unused" is a
        copy nothing points at (garbage collection can reclaim it), including a
        duplicate whose records use a copy elsewhere; "history-only" is used
        only by workflow runs; "shared" is pointed at by the live records of
        more than one collection (each counts it as theirs)."""
        from civex.db.models import StoredObject

        here = (FileReference.sha256 == StoredObject.sha256) & (
            (FileReference.volume == StoredObject.volume)
            | FileReference.volume.is_(None)
        )
        by_record = (
            select(FileReference.id)
            .where(here, FileReference.record_id.is_not(None))
            .exists()
        )
        by_job = (
            select(FileReference.id)
            .where(
                FileReference.sha256 == StoredObject.sha256,
                FileReference.job_id.is_not(None),
            )
            .exists()
        )
        collections = (
            select(func.count(func.distinct(Record.dataset_id)))
            .join(FileReference, FileReference.record_id == Record.id)
            .where(
                FileReference.sha256 == StoredObject.sha256,
                FileReference.volume == StoredObject.volume,
                Record.deleted_at.is_(None),
            )
            .scalar_subquery()
        )
        unused, history = ~by_record & ~by_job, ~by_record & by_job
        shared = collections > 1

        def total(cond: Any, value: Any) -> Any:
            return func.coalesce(func.sum(case((cond, value), else_=0)), 0)

        rows = self._s.execute(
            select(
                StoredObject.volume,
                total(unused, 1),
                total(unused, StoredObject.size),
                total(history, 1),
                total(history, StoredObject.size),
                total(shared, 1),
                total(shared, StoredObject.size),
            ).group_by(StoredObject.volume)
        )
        return {v: tuple(int(x) for x in rest) for v, *rest in rows}  # type: ignore[misc]

    def volume_breakdowns(
        self, collection_ids: list[str] | None
    ) -> dict[str, tuple[int, list[tuple[str, int, int, int, int]]]]:
        """Where collections' files are, from the catalog in a few grouped
        queries (no file is read), for the given collections or all of them.
        Per collection id: the number of distinct files its records use, and per
        volume (volume, files, bytes, files another collection's records use
        too, and their bytes). A file counts on the drive of the copy its records point at, so a
        duplicate on another drive that they don't use isn't theirs; only if
        its records point at copies on two drives does it count on both."""
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

        out: dict[str, tuple[int, list[tuple[str, int, int, int, int]]]] = {}
        for cid, n in self._s.execute(
            select(mine.c.cid, func.count()).group_by(mine.c.cid)
        ):
            out[str(cid)] = (int(n), [])

        # one row per (collection, copy) its live records point at
        placed = scoped(
            select(
                Record.dataset_id.label("cid"),
                FileReference.sha256.label("sha"),
                FileReference.volume.label("volume"),
            )
            .join(Record, Record.id == FileReference.record_id)
            .where(Record.deleted_at.is_(None), FileReference.volume.is_not(None))
            .distinct()
        ).subquery()
        # how many collections point at each of those copies, to spot shared ones
        users = (
            select(
                FileReference.sha256.label("sha"),
                FileReference.volume.label("volume"),
                func.count(func.distinct(Record.dataset_id)).label("n"),
            )
            .join(Record, Record.id == FileReference.record_id)
            .where(
                FileReference.sha256.in_(select(placed.c.sha)),
                Record.deleted_at.is_(None),
            )
            .group_by(FileReference.sha256, FileReference.volume)
            .subquery()
        )
        rows = self._s.execute(
            select(
                placed.c.cid,
                placed.c.volume,
                func.count(),
                func.coalesce(func.sum(StoredObject.size), 0),
                func.coalesce(func.sum(case((users.c.n > 1, 1), else_=0)), 0),
                func.coalesce(
                    func.sum(case((users.c.n > 1, StoredObject.size), else_=0)), 0
                ),
            )
            .join(
                StoredObject,
                (StoredObject.sha256 == placed.c.sha)
                & (StoredObject.volume == placed.c.volume),
            )
            .join(
                users,
                (users.c.sha == placed.c.sha) & (users.c.volume == placed.c.volume),
            )
            .group_by(placed.c.cid, placed.c.volume)
        )
        for cid, volume, files, size, shared, shared_size in rows:
            out[str(cid)][1].append(
                (volume, int(files), int(size), int(shared), int(shared_size))
            )
        return out

    def _live_users(
        self, shas: Iterable[str]
    ) -> list[tuple[str, uuid.UUID, uuid.UUID | None, str | None]]:
        """(file, record, its collection, the copy's volume) for each live
        record using one of
        these files, found from the files' side: their rows by hash, then just
        those records. One join instead let SQLite (without statistics) start
        from `deleted_at IS NULL`, so every live record in the project was
        visited for each batch of files: seconds for a few thousand files."""
        wanted = list(dict.fromkeys(shas))
        uses: list[tuple[str, uuid.UUID, str | None]] = []
        for i in range(0, len(wanted), 500):
            for sha, record_id, volume in self._s.execute(
                select(
                    FileReference.sha256, FileReference.record_id, FileReference.volume
                ).where(
                    FileReference.sha256.in_(wanted[i : i + 500]),
                    FileReference.record_id.is_not(None),
                )
            ):
                if record_id is not None:
                    uses.append((sha, record_id, volume))
        ids = list({record_id for _, record_id, _ in uses})
        live: dict[uuid.UUID, uuid.UUID | None] = {}
        for i in range(0, len(ids), 500):
            for record_id, dataset_id in self._s.execute(
                select(Record.id, Record.dataset_id).where(
                    Record.id.in_(ids[i : i + 500]), Record.deleted_at.is_(None)
                )
            ):
                live[record_id] = dataset_id
        return [(sha, rid, live[rid], vol) for sha, rid, vol in uses if rid in live]

    def pointers(self, shas: Iterable[str]) -> dict[str, list[Pointer]]:
        """Every owner of each file and the copy it points at: live and deleted
        records (with their collection) and workflow runs. Found from the
        files' side, a query per 500 files."""
        wanted = list(dict.fromkeys(shas))
        out: dict[str, list[Pointer]] = {}
        for i in range(0, len(wanted), 500):
            rows = self._s.execute(
                select(
                    FileReference.id,
                    FileReference.sha256,
                    FileReference.volume,
                    FileReference.record_id,
                    Record.dataset_id,
                    Record.deleted_at,
                )
                .outerjoin(Record, Record.id == FileReference.record_id)
                .where(FileReference.sha256.in_(wanted[i : i + 500]))
            )
            for ref_id, sha, volume, record_id, dataset_id, deleted_at in rows:
                out.setdefault(sha, []).append(
                    Pointer(
                        id=ref_id,
                        sha256=sha,
                        volume=volume,
                        record_id=record_id,
                        collection_id=str(dataset_id) if dataset_id else None,
                        live=record_id is not None and deleted_at is None,
                    )
                )
        return out

    def point_rows(self, ids: Iterable[uuid.UUID], volume: str) -> None:
        """Point these owners (file_references rows, by id) at the copy on
        `volume`."""
        wanted = list(dict.fromkeys(ids))
        for i in range(0, len(wanted), 500):
            self._s.execute(
                update(FileReference)
                .where(FileReference.id.in_(wanted[i : i + 500]))
                .values(volume=volume)
            )

    def pointing_at(self, sha256: str, volume: str) -> int:
        """How many owners point at this copy."""
        return self._s.execute(
            select(func.count()).where(
                FileReference.sha256 == sha256, FileReference.volume == volume
            )
        ).scalar_one()

    def records_using(self, shas: Iterable[str]) -> dict[str, set[uuid.UUID]]:
        """For each file, the live records that use it (any copy)."""
        out: dict[str, set[uuid.UUID]] = {}
        for sha, record_id, _, _ in self._live_users(shas):
            out.setdefault(sha, set()).add(record_id)
        return out

    def copy_users(
        self, shas: Iterable[str]
    ) -> dict[tuple[str, str | None], set[uuid.UUID]]:
        """For each copy of these files, (sha256, volume), the live records
        pointing at it (volume None: not here yet)."""
        out: dict[tuple[str, str | None], set[uuid.UUID]] = {}
        for sha, record_id, _, volume in self._live_users(shas):
            out.setdefault((sha, volume), set()).add(record_id)
        return out

    def collections_using(self, shas: Iterable[str]) -> dict[str, set[str]]:
        """For each file, the ids of the collections whose records use it."""
        out: dict[str, set[str]] = {}
        for sha, _, dataset_id, _ in self._live_users(shas):
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
        an import that bypassed the ORM). Which copy each record uses is kept;
        a row new to the table points at the file's newest copy. Returns the
        number of rows."""
        from civex.db.models import StoredObject

        kept: dict[tuple[uuid.UUID | None, uuid.UUID | None, str], str] = {
            (record_id, job_id, sha): volume
            for record_id, job_id, sha, volume in self._s.execute(
                select(
                    FileReference.record_id,
                    FileReference.job_id,
                    FileReference.sha256,
                    FileReference.volume,
                ).where(FileReference.volume.is_not(None))
            )
        }
        newest: dict[str, str] = {
            sha: volume
            for sha, volume in self._s.execute(
                select(StoredObject.sha256, StoredObject.volume).order_by(
                    StoredObject.created_at, StoredObject.volume
                )
            )
        }
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
                out = []
                for oid, payload in rows:
                    rid = oid if owner == "record_id" else None
                    jid = oid if owner == "job_id" else None
                    for sha in collect_sha256_refs(payload):
                        out.append(
                            {
                                "id": uuid.uuid4(),
                                "sha256": sha,
                                "record_id": rid,
                                "job_id": jid,
                                "volume": kept.get((rid, jid, sha), newest.get(sha)),
                            }
                        )
                if out:
                    self._s.execute(insert(FileReference), out)
                    total += len(out)
        return total
