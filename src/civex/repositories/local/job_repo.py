from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from civex.db.models import WorkflowJob
from civex.domain.dtos import WorkflowJobDTO


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LocalWorkflowJobRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def enqueue(
        self,
        workflow_name: str,
        record_id: uuid.UUID,
        schema_name: str,
        trigger: str,
        input_data: dict | None = None,
        depth: int = 0,
    ) -> WorkflowJobDTO:
        row = WorkflowJob(
            workflow_name=workflow_name,
            record_id=record_id,
            schema_name=schema_name,
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

    def mark_completed(self, job_id: uuid.UUID, log: str | None = None) -> None:
        row = self._s.query(WorkflowJob).filter_by(id=job_id).first()
        if row:
            row.status = "completed"
            row.finished_at = _now()
            row.log = log
            self._s.flush()

    def mark_failed(
        self,
        job_id: uuid.UUID,
        error: str,
        log: str | None = None,
        error_details: dict | None = None,
    ) -> None:
        row = self._s.query(WorkflowJob).filter_by(id=job_id).first()
        if row:
            row.status = "failed"
            row.finished_at = _now()
            row.error = error[:2000]
            row.error_details = error_details
            row.log = log
            self._s.flush()

    def list_all(
        self,
        status: str | None = None,
        record_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[WorkflowJobDTO]:
        q = self._s.query(WorkflowJob)
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
        row = self._s.query(WorkflowJob).filter_by(id=job_id).first()
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


def _to_dto(row: WorkflowJob) -> WorkflowJobDTO:
    return WorkflowJobDTO(
        id=row.id,
        workflow_name=row.workflow_name,
        record_id=row.record_id,
        schema_name=row.schema_name,
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
    )
