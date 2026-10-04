"""Clean-up by age: deleted items, change history and workflow runs.

What is kept, and for how long, is the `[retention]` settings; a clean-up
applies them, or deletes everything older than dates a person gives, per kind.
It never runs by itself. Every kind defaults to keep-forever, so nothing is
removed until someone asks.

The order matters: deleted collections and schemas go first (their records go
with them, without a line each in history), then the records deleted on their
own, then history older than the cutoff, so the purges just made are the newest
entries and are kept. Files nothing refers to any more are the file clean-up's
job (`GCService`); run it afterwards to reclaim the space.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from civex.config import RetentionConfig
from civex.domain.dtos import RetentionCutoffs, RetentionReportDTO
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.repositories.protocols import AuditRepository, WorkflowJobRepository
from civex.services.dataset_service import DatasetService
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService


def _utc(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


class RetentionService:
    def __init__(
        self,
        record_svc: RecordService,
        dataset_svc: DatasetService,
        schema_svc: SchemaService,
        audit: AuditRepository,
        jobs: WorkflowJobRepository,
        retention: RetentionConfig,
        protect_unsynced: bool,
    ) -> None:
        self._records = record_svc
        self._datasets = dataset_svc
        self._schemas = schema_svc
        self._audit = audit
        self._jobs = jobs
        self._retention = retention
        # With a remote, history not yet pushed is the only copy a pull on the
        # other side would be missing, so it is kept.
        self._protect_unsynced = protect_unsynced

    def settings_cutoffs(self, now: datetime | None = None) -> RetentionCutoffs:
        """The cutoffs the settings imply right now: a kind left at keep-forever
        (or, for deleted items, without auto-delete) has none."""
        now = now or datetime.now(timezone.utc)
        r = self._retention
        return RetentionCutoffs(
            deleted_before=now - timedelta(days=r.purge_after_days)
            if r.auto_purge_deleted
            else None,
            audit_before=now - timedelta(days=r.audit_days) if r.audit_days else None,
            runs_before=now - timedelta(days=r.run_days) if r.run_days else None,
        )

    def forget_purged(self, dry_run: bool = True) -> int:
        """Delete the history of records that were permanently deleted before
        that removed it. Permanent deletes now remove it themselves; this is for
        what they left behind. Returns how many entries there are (or were)."""
        found = self._audit.count_orphaned_records()
        if not dry_run and found:
            found = self._audit.forget_orphaned_records()
        return found

    def cutoffs(
        self,
        from_settings: bool = False,
        deleted_before: datetime | None = None,
        audit_before: datetime | None = None,
        runs_before: datetime | None = None,
    ) -> RetentionCutoffs:
        """What to clean up: the settings' cutoffs (`from_settings`), and/or a
        date given outright for any kind, which wins over the setting for it."""
        base = self.settings_cutoffs() if from_settings else RetentionCutoffs()
        return RetentionCutoffs(
            deleted_before=deleted_before or base.deleted_before,
            audit_before=audit_before or base.audit_before,
            runs_before=runs_before or base.runs_before,
        )

    def run(
        self, cutoffs: RetentionCutoffs, dry_run: bool = True
    ) -> RetentionReportDTO:
        """Remove what is older than the cutoffs, or with `dry_run` (the
        default) only count it. A cutoff of None leaves that kind alone."""
        report = RetentionReportDTO(dry_run=dry_run)
        if cutoffs.deleted_before:
            self._deleted(_utc(cutoffs.deleted_before), report, dry_run)
        if cutoffs.audit_before:
            self._history(_utc(cutoffs.audit_before), report, dry_run)
        if cutoffs.runs_before:
            self._runs(_utc(cutoffs.runs_before), report, dry_run)
        return report

    def _deleted(
        self, cutoff: datetime, report: RetentionReportDTO, dry_run: bool
    ) -> None:
        collections = [
            d
            for d in self._datasets.list_deleted()
            if d.deleted_at and _utc(d.deleted_at) < cutoff
        ]
        schemas = [
            s
            for s in self._schemas.list_deleted()
            if s.deleted_at and _utc(s.deleted_at) < cutoff
        ]
        report.deleted_collections = len(collections)
        report.deleted_schemas = len(schemas)
        report.deleted_records = len(self._records.purgeable_deleted(cutoff))
        if dry_run:
            return
        for collection in collections:
            try:
                self._datasets.purge(collection.name)
            except (NotFoundError, ValidationError) as e:
                report.deleted_collections -= 1
                report.skipped.append(f"Collection '{collection.name}': {e}")
        for schema in schemas:
            try:
                self._schemas.purge(schema.name)
            except (NotFoundError, ValidationError) as e:
                report.deleted_schemas -= 1
                report.skipped.append(f"Schema '{schema.name}': {e}")
        # Whatever the collections and schemas did not take with them.
        left = [rid for rid, _, _ in self._records.purgeable_deleted(cutoff)]
        self._records.purge_records(left)

    def _history(
        self, cutoff: datetime, report: RetentionReportDTO, dry_run: bool
    ) -> None:
        counted = self._audit.count_prunable(cutoff, self._protect_unsynced)
        report.audit_entries = counted["entries"]
        report.audit_kept_restorable = counted["kept_restorable"]
        report.audit_kept_unsynced = counted["kept_unsynced"]
        if dry_run:
            return
        report.audit_entries, report.audit_batches = self._audit.prune(
            cutoff, self._protect_unsynced
        )

    def _runs(
        self, cutoff: datetime, report: RetentionReportDTO, dry_run: bool
    ) -> None:
        report.runs, report.run_steps = self._jobs.count_finished_before(cutoff)
        if not dry_run:
            self._jobs.delete_finished_before(cutoff)
