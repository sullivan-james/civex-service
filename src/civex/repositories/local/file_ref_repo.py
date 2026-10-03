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
