from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from civex.db.models import Record, StepExecution, WorkflowJob
from civex.domain.dtos import WorkflowJobDTO

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
    ) -> None:
        row = self._s.query(WorkflowJob).filter_by(id=job_id).first()
        if row:
            row.status = "completed"
            row.finished_at = _now()
            row.log = log
            _replace_step_executions(self._s, job_id, step_executions)
            self._s.flush()

    def mark_failed(
        self,
        job_id: uuid.UUID,
        error_details: dict,
        log: str | None = None,
        step_executions: list[dict] | None = None,
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
            _replace_step_executions(self._s, job_id, step_executions)
            self._s.flush()

    def list_all(
        self,
        status: str | None = None,
        record_id: str | None = None,
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
        q = q.order_by(WorkflowJob.created_at.desc()).offset(offset)
        if limit is not None:
            q = q.limit(limit)
        return [_to_dto(r) for r in q.all()]

    def count(self, status: str | None = None, record_id: str | None = None) -> int:
        q = self._s.query(WorkflowJob)
        if status:
            q = q.filter_by(status=status)
        if record_id:
            try:
                q = q.filter_by(record_id=uuid.UUID(record_id))
            except ValueError:
                return 0
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

    def failure_counts_by_plugin(self) -> dict[str, int]:
        """Number of failed step executions per plugin, across every job --
        the aggregate query the JSON blob made expensive (CIVEX-170): this
        is a GROUP BY on an indexed-able column instead of a full scan
        parsing every job's JSON."""
        rows = (
            self._s.query(StepExecution.plugin, func.count(StepExecution.id))
            .filter(StepExecution.status == "failed")
            .group_by(StepExecution.plugin)
            .order_by(func.count(StepExecution.id).desc())
            .all()
        )
        return {plugin: count for plugin, count in rows}


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
    )
