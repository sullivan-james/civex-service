from __future__ import annotations

import time
from typing import Any

from civex.domain.dtos import GCReport, StoredObjectInfo
from civex.repositories.protocols import (
    FileObjectStore,
    RecordRepository,
    WorkflowJobRepository,
)

_DAY_SECONDS = 86400
# Threshold for reclaiming abandoned put_stream() .part files, independent of
# grace_days: unlike a real object, nothing can ever reference a half-written
# scratch file, so there's no "wait, something might still need this" case to
# protect against -- just enough headroom that a slow-but-live upload isn't
# mistaken for an abandoned one.
_STALE_SCRATCH_SECONDS = _DAY_SECONDS


def _collect_sha256_refs(value: Any, out: set[str]) -> None:
    """Recursively find every `{"sha256": ...}` dict nested anywhere in
    `value` -- covers `file` fields (a single FileRef dict), `file_list`
    fields (a list of them), and workflow `input_data` (FileRef dicts
    nested under arbitrary input names), all without needing schema
    field-type lookups to know where to look."""
    if isinstance(value, dict):
        sha = value.get("sha256")
        if isinstance(sha, str):
            out.add(sha)
        for v in value.values():
            _collect_sha256_refs(v, out)
    elif isinstance(value, list):
        for v in value:
            _collect_sha256_refs(v, out)


class GCService:
    """Reclaims object-store blobs no longer reachable from any live root.

    Roots: live records, soft-deleted records still in "Recently Deleted"
    (restorable), and every workflow job's `input_data` (a failed or
    completed job can be rerun at any time -- see the jobs `rerun` endpoint
    -- so its seeded file inputs must still resolve).

    Deliberately NOT a root: audit_log.old_data/new_data and
    workflow_jobs.step_executions. Both retain full historical snapshots
    forever with no expiry, so treating them as roots would make GC nearly
    a no-op -- almost every file ever attached to a record still appears in
    that record's audit history. A blob collected while still referenced
    only by history means an old audit diff or job log can point at a
    sha256 that no longer resolves; that's the accepted tradeoff of running
    GC at all.
    """

    def __init__(
        self,
        store: FileObjectStore,
        record_repo: RecordRepository,
        job_repo: WorkflowJobRepository,
    ) -> None:
        self._store = store
        self._records = record_repo
        self._jobs = job_repo

    def _referenced_hashes(self) -> set[str]:
        refs: set[str] = set()
        for record in self._records.list_all():
            _collect_sha256_refs(record.data, refs)
        for record in self._records.list_deleted():
            _collect_sha256_refs(record.data, refs)
        for job in self._jobs.list_all(limit=None):
            if job.input_data:
                _collect_sha256_refs(job.input_data, refs)
        return refs

    def run(self, dry_run: bool = True, grace_days: int = 14) -> GCReport:
        referenced = self._referenced_hashes()
        cutoff = time.time() - grace_days * _DAY_SECONDS

        collectible: list[StoredObjectInfo] = []
        protected_by_grace = 0
        scanned = 0

        for obj in self._store.list_objects():
            scanned += 1
            if obj.sha256 in referenced:
                continue
            if obj.mtime > cutoff:
                protected_by_grace += 1
                continue
            collectible.append(obj)

        if not dry_run:
            for obj in collectible:
                self._store.delete(obj.sha256, volume=obj.volume)

        stale_scratch_removed = self._store.sweep_stale_scratch(
            _STALE_SCRATCH_SECONDS, dry_run=dry_run
        )

        return GCReport(
            dry_run=dry_run,
            grace_days=grace_days,
            scanned=scanned,
            referenced=len(referenced),
            protected_by_grace=protected_by_grace,
            deleted=collectible,
            stale_scratch_removed=stale_scratch_removed,
        )
