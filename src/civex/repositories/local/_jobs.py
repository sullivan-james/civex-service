from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from civex.db.models import StepExecution, WorkflowJob


def bulk_delete_jobs(session: Session, *criteria: Any) -> None:
    """Delete every WorkflowJob matching `criteria`, step executions first.

    step_executions.job_id is a plain FK (no ON DELETE CASCADE), and the ORM's
    delete-orphan cascade only runs for `session.delete(job)` -- not for the
    bulk DELETE the purge paths use to avoid loading every job. Deleting the
    jobs directly therefore fails with an FK violation as soon as any of them
    has a recorded step. (file_references and job_affected_schemas *do*
    cascade at the database level.)
    """
    job_ids = select(WorkflowJob.id).where(*criteria)
    session.execute(delete(StepExecution).where(StepExecution.job_id.in_(job_ids)))
    session.execute(delete(WorkflowJob).where(*criteria))
