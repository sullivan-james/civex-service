from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from civex.db.models import Record, StepExecution, WorkflowJob
from civex.domain.dtos import WorkflowJobDTO
from civex.repositories.local._bucketing import day_bucket, rebucket
from civex.repositories.protocols import JobStatusRow, PluginFailureRow

# schema_name isn't a column (CIVEX-171) -- every query needs the record's
# schema loaded so _to_dto can resolve it via the join.
_WITH_SCHEMA = joinedload(WorkflowJob.record).joinedload(Record.schema)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LocalWorkflowJobRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def enqueue(
        self,
        workflow_name: str,
        record_id: uuid.UUID,
        trigger: str,
        input_data: dict | None = None,
        depth: int = 0,
    ) -> WorkflowJobDTO:
        row = WorkflowJob(
            workflow_name=workflow_name,
            record_id=record_id,
            trigger=trigger,
            status="pending",
            input_data=input_data,
            depth=depth,
        )
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    def claim_pending(self) -> WorkflowJobDTO | None:
        """Claim the oldest pending job by marking it running. Not safe for concurrent workers."""
        row = (
            self._s.query(WorkflowJob)
            .filter_by(status="pending")
            .order_by(WorkflowJob.created_at)
            .first()
        )
        if row is None:
            return None
        row.status = "running"
        row.started_at = _now()
        self._s.flush()
        return _to_dto(row)

    def mark_completed(
        self,
        job_id: uuid.UUID,
        log: str | None = None,
        step_executions: list[dict] | None = None,
        affected_records: list[dict] | None = None,
    ) -> None:
        row = self._s.query(WorkflowJob).filter_by(id=job_id).first()
        if row:
            row.status = "completed"
            row.finished_at = _now()
            row.log = log
            row.affected_records = affected_records or None
            _replace_step_executions(self._s, job_id, step_executions)
            self._s.flush()

    def mark_failed(
        self,
        job_id: uuid.UUID,
        error_details: dict,
        log: str | None = None,
        step_executions: list[dict] | None = None,
        affected_records: list[dict] | None = None,
    ) -> None:
        row = self._s.query(WorkflowJob).filter_by(id=job_id).first()
        if row:
            row.status = "failed"
            row.finished_at = _now()
            # `error` and `error_details["message"]` are the same string --
            # writing both here, in the one place a job is marked failed, is
            # what keeps them from disagreeing (CIVEX-171).
            row.error = error_details["message"][:2000]
            row.error_details = error_details
            row.log = log
            # A failed run may still have created/updated records before the
            # step that failed -- same partial-progress contract as
            # step_executions, so the audit trail doesn't hide real writes.
            row.affected_records = affected_records or None
            _replace_step_executions(self._s, job_id, step_executions)
            self._s.flush()

    def list_all(
        self,
        status: str | None = None,
        record_id: str | None = None,
        affected_record_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[WorkflowJobDTO]:
        q = self._s.query(WorkflowJob).options(
            selectinload(WorkflowJob.steps), _WITH_SCHEMA
        )
        if status:
            q = q.filter_by(status=status)
        if record_id:
            try:
                q = q.filter_by(record_id=uuid.UUID(record_id))
            except ValueError:
                return []
        q = q.order_by(WorkflowJob.created_at.desc())
        if affected_record_id:
            # affected_records is a small per-job JSON list -- no index to
            # filter on, so this scans and checks in Python rather than
            # adding a JSON containment query (mirrors record_repo's SQLite
            # fallback for the same tradeoff, CIVEX-169).
            rows = [r for r in q.all() if _touches(r, affected_record_id)]
            rows = rows[offset : offset + limit if limit is not None else None]
            return [_to_dto(r) for r in rows]
        q = q.offset(offset)
        if limit is not None:
            q = q.limit(limit)
        return [_to_dto(r) for r in q.all()]

    def count(
        self,
        status: str | None = None,
        record_id: str | None = None,
        affected_record_id: str | None = None,
    ) -> int:
        q = self._s.query(WorkflowJob)
        if status:
            q = q.filter_by(status=status)
        if record_id:
            try:
                q = q.filter_by(record_id=uuid.UUID(record_id))
            except ValueError:
                return 0
        if affected_record_id:
            return sum(1 for r in q.all() if _touches(r, affected_record_id))
        return q.count()

    def get_by_id(self, job_id: uuid.UUID) -> WorkflowJobDTO | None:
        row = (
            self._s.query(WorkflowJob)
            .options(selectinload(WorkflowJob.steps), _WITH_SCHEMA)
            .filter_by(id=job_id)
            .first()
        )
        return _to_dto(row) if row else None

    def count_active_for_workflow(self, workflow_name: str) -> int:
        """Pending or running jobs queued against this workflow name -- these
        would fail to find their workflow definition mid-run if the file
        were deleted out from under them."""
        return (
            self._s.query(WorkflowJob)
            .filter_by(workflow_name=workflow_name)
            .filter(WorkflowJob.status.in_(("pending", "running")))
            .count()
        )

    def failure_counts_by_plugin(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        bucket: str | None = None,
    ) -> dict[str, int] | list[PluginFailureRow]:
        """Number of failed step executions per plugin -- the aggregate query
        the JSON blob made expensive (CIVEX-170): this is a GROUP BY on a
        plain column instead of a full scan parsing every job's JSON.

        With `bucket` left as None (the original call shape, still used by
        `civex worker stats`), returns the all-time flat `plugin -> count`
        dict, optionally scoped to `[start, end)`. Pass a bucket size
        ("day"/"week"/"month") to get the same counts broken into a time
        series instead, for the analytics endpoint.
        """
        day = day_bucket(WorkflowJob.created_at)
        q = (
            self._s.query(day, StepExecution.plugin, func.count(StepExecution.id))
            .join(WorkflowJob, StepExecution.job_id == WorkflowJob.id)
            .filter(StepExecution.status == "failed")
        )
        if start is not None:
            q = q.filter(WorkflowJob.created_at >= start)
        if end is not None:
            q = q.filter(WorkflowJob.created_at < end)
        rows = q.group_by(day, StepExecution.plugin).all()
        if bucket is None:
            totals: dict[str, int] = {}
            for _, plugin, count in rows:
                totals[plugin] = totals.get(plugin, 0) + count
            return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))
        return rebucket([(d, plugin, count) for d, plugin, count in rows], bucket)

    def status_counts_by_period(
        self,
        start: datetime | None,
        end: datetime | None,
        workflow_name: str | None,
        trigger: str | None,
        status: str | None,
    ) -> list[JobStatusRow]:
        """Job counts per day, broken out by status -- backs the job-status
        trend widget. Filters directly on `workflow_jobs` columns, no join
        needed."""
        day = day_bucket(WorkflowJob.created_at)
        q = self._s.query(day, WorkflowJob.status, func.count(WorkflowJob.id))
        if start is not None:
            q = q.filter(WorkflowJob.created_at >= start)
        if end is not None:
            q = q.filter(WorkflowJob.created_at < end)
        if workflow_name is not None:
            q = q.filter(WorkflowJob.workflow_name == workflow_name)
        if trigger is not None:
            q = q.filter(WorkflowJob.trigger == trigger)
        if status is not None:
            q = q.filter(WorkflowJob.status == status)
        rows = q.group_by(day, WorkflowJob.status).order_by(day).all()
        return [(d, s, count) for d, s, count in rows]

    def trigger_counts(
        self,
        start: datetime | None,
        end: datetime | None,
        workflow_name: str | None,
        status: str | None,
        trigger: str | None,
    ) -> list[tuple[str, int]]:
        """Job counts grouped by trigger type -- backs the trigger-breakdown
        widget. Filters directly on `workflow_jobs` columns, no join
        needed."""
        q = self._s.query(WorkflowJob.trigger, func.count(WorkflowJob.id))
        if start is not None:
            q = q.filter(WorkflowJob.created_at >= start)
        if end is not None:
            q = q.filter(WorkflowJob.created_at < end)
        if workflow_name is not None:
            q = q.filter(WorkflowJob.workflow_name == workflow_name)
        if status is not None:
            q = q.filter(WorkflowJob.status == status)
        if trigger is not None:
            q = q.filter(WorkflowJob.trigger == trigger)
        rows = q.group_by(WorkflowJob.trigger).all()
        return [(t, count) for t, count in rows]

    def step_durations(
        self,
        start: datetime | None,
        end: datetime | None,
        plugin: str | None,
        status: str | None,
    ) -> list[float]:
        """Raw `duration_seconds` values for step executions matching the
        filters -- the analytics service turns this into avg/min/max/
        percentile stats. Reads the column directly (CIVEX-170 normalized it
        out of the old per-job JSON blob), rather than parsing JSON per row."""
        q = (
            self._s.query(StepExecution.duration_seconds)
            .join(WorkflowJob, StepExecution.job_id == WorkflowJob.id)
            .filter(StepExecution.duration_seconds.isnot(None))
        )
        if plugin is not None:
            q = q.filter(StepExecution.plugin == plugin)
        if status is not None:
            q = q.filter(StepExecution.status == status)
        if start is not None:
            q = q.filter(WorkflowJob.created_at >= start)
        if end is not None:
            q = q.filter(WorkflowJob.created_at < end)
        return [d for (d,) in q.all()]


def _touches(row: WorkflowJob, record_id: str) -> bool:
    return any(e.get("record_id") == record_id for e in row.affected_records or [])


def _replace_step_executions(
    session: Session, job_id: uuid.UUID, step_executions: list[dict] | None
) -> None:
    """Overwrites this job's step_executions rows -- mirrors the old
    `row.step_executions = step_executions` assignment now that the per-step
    records live in their own table (CIVEX-170). `mark_completed`/`mark_failed`
    are each only ever called once per job, but delete-then-insert keeps this
    safe to call again."""
    session.query(StepExecution).filter_by(job_id=job_id).delete()
    if not step_executions:
        return
    for position, step in enumerate(step_executions):
        session.add(
            StepExecution(
                job_id=job_id,
                position=position,
                step_id=step["step_id"],
                plugin=step["plugin"],
                status=step["status"],
                duration_seconds=step.get("duration_seconds"),
                error=step.get("error"),
                error_details=step.get("error_details"),
                inputs=step.get("inputs"),
                outputs=step.get("outputs"),
                depends_on=step.get("depends_on"),
            )
        )


def _to_dto(row: WorkflowJob) -> WorkflowJobDTO:
    step_executions = (
        [
            {
                "step_id": s.step_id,
                "plugin": s.plugin,
                "status": s.status,
                "inputs": s.inputs,
                "outputs": s.outputs,
                "duration_seconds": s.duration_seconds,
                "error": s.error,
                "depends_on": s.depends_on,
            }
            for s in row.steps
        ]
        if row.steps
        else None
    )
    return WorkflowJobDTO(
        id=row.id,
        workflow_name=row.workflow_name,
        record_id=row.record_id,
        schema_name=row.record.schema.name,
        trigger=row.trigger,
        status=row.status,
        error=row.error,
        error_details=row.error_details,
        log=row.log,
        input_data=row.input_data,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        depth=row.depth,
        step_executions=step_executions,
        affected_records=row.affected_records,
    )
