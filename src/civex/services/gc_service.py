from __future__ import annotations

import logging
import time
from civex.domain.dtos import GCReport, StoredObjectInfo
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.repositories.protocols import FileObjectStore, FileReferenceRepository

log = logging.getLogger(__name__)

_DAY_SECONDS = 86400
# Threshold for reclaiming abandoned put_stream() .part files, independent of
# grace_days: unlike a real object, nothing can ever reference a half-written
# scratch file, so there's no "wait, something might still need this" case to
# protect against -- just enough headroom that a slow-but-live upload isn't
# mistaken for an abandoned one.
_STALE_SCRATCH_SECONDS = _DAY_SECONDS
# Objects checked against the reference table per query -- bounds GC's memory
# at O(batch) however large the store or the record/job history is.
_BATCH = 2000


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

    def __init__(self, store: FileObjectStore, refs: FileReferenceRepository) -> None:
        self._store = store
        self._refs = refs

    def rebuild_references(self) -> int:
        """Recompute the reference table from every record and job input.
        Not needed in normal operation (it's maintained on every write);
        run it if the table may have drifted, before a GC pass."""
        return self._refs.rebuild()

    def run(
        self, dry_run: bool = True, grace_days: int = 14, volume: str | None = None
    ) -> GCReport:
        """Collect unreferenced objects, from every volume or just `volume`."""
        if grace_days < 0:
            # A negative value would erase the grace period's whole purpose
            # (protecting a freshly-uploaded-but-not-yet-attached object
            # from being raced into deletion) rather than just shortening
            # it -- validated here, the one place both the CLI and the API
            # route through, so neither caller can bypass it independently.
            raise ValidationError("grace_days must be >= 0")
        if volume is not None and volume not in self._store.volume_names():
            raise NotFoundError(f"Volume '{volume}' not found")

        with self._store.gc_lock():
            cutoff = time.time() - grace_days * _DAY_SECONDS
            errors: list[str] = []
            collectible: list[StoredObjectInfo] = []
            counts = {"scanned": 0, "protected": 0}

            def process(batch: list[StoredObjectInfo]) -> None:
                # A reference lookup that fails means this batch might hold
                # something still live: skip it, and stop deleting for the
                # rest of the run (same contract as the old per-source read
                # errors -- an incomplete picture must never delete).
                try:
                    live = self._refs.referenced_subset(o.sha256 for o in batch)
                except Exception as e:
                    log.error(
                        "GC: failed to read file references: %s", e, exc_info=True
                    )
                    errors.append(f"file references: {e}")
                    return
                for obj in batch:
                    if obj.sha256 in live:
                        continue
                    # No grace period means none: comparing with "now" would
                    # still spare a file just written whose timestamp is a
                    # little ahead of time.time() (Windows file times).
                    if grace_days and obj.mtime > cutoff:
                        counts["protected"] += 1
                        continue
                    collectible.append(obj)
                    if not dry_run and not errors:
                        self._store.delete(obj.sha256, volume=obj.volume)

            batch: list[StoredObjectInfo] = []
            for obj in self._store.iter_objects():
                if volume is not None and obj.volume != volume:
                    continue
                counts["scanned"] += 1
                batch.append(obj)
                if len(batch) >= _BATCH:
                    process(batch)
                    batch = []
            if batch:
                process(batch)

            # Repair inventory drift as part of the same pass, so volume
            # usage accounting can't silently diverge from disk.
            if not dry_run and not errors:
                self._store.reconcile_inventory()

            # Abandoned uploads aren't on any one volume; a clean-up of a single
            # volume leaves them for a store-wide pass.
            stale_scratch_removed = (
                0
                if volume is not None
                else self._store.sweep_stale_scratch(
                    _STALE_SCRATCH_SECONDS, dry_run=dry_run or bool(errors)
                )
            )

            return GCReport(
                dry_run=dry_run,
                grace_days=grace_days,
                scanned=counts["scanned"],
                referenced=self._refs.count_referenced(),
                protected_by_grace=counts["protected"],
                deleted=collectible,
                stale_scratch_removed=stale_scratch_removed,
                errors=errors,
                volume=volume,
            )
