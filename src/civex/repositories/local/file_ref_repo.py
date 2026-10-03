from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import delete, func, insert, select
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
            .where(Record.dataset_id.in_(ids))
            .distinct()
            .order_by(FileReference.sha256)
            .limit(limit)
        )
        if after is not None:
            query = query.where(FileReference.sha256 > after)
        return [sha for (sha,) in self._s.execute(query)]

    def collections_using(self, shas: Iterable[str]) -> dict[str, set[str]]:
        """For each file, the ids of the collections whose records use it."""
        wanted = list(shas)
        out: dict[str, set[str]] = {}
        if not wanted:
            return out
        rows = self._s.execute(
            select(FileReference.sha256, Record.dataset_id)
            .join(Record, Record.id == FileReference.record_id)
            .where(FileReference.sha256.in_(wanted))
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
