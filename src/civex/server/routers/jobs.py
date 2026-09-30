from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError
from civex.server.background import run_pending_jobs
from civex.server.deps import get_ctx
from civex.server.models import WorkflowJobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/count")
def count_jobs(
    status: str | None = None,
    record_id: str | None = None,
    affected_record_id: str | None = None,
    affected_schema: str | None = None,
    ctx: AppContext = Depends(get_ctx),
):
    return {
        "total": ctx.job_svc.count_jobs(
            status=status,
            record_id=record_id,
            affected_record_id=affected_record_id,
            affected_schema=affected_schema,
        )
    }


@router.get("", response_model=list[WorkflowJobResponse])
def list_jobs(
    status: str | None = None,
    record_id: str | None = None,
    affected_record_id: str | None = None,
    affected_schema: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    ctx: AppContext = Depends(get_ctx),
):
    """`record_id` filters to runs *triggered by* that record; `affected_record_id`
    filters to runs that created or updated that record -- the two directions of
    the run/record audit trail (a record can be both for different runs).
    `affected_schema` filters to runs that wrote to that schema (indexed).
    Results are paginated: `limit` defaults to 50 and is capped at 500."""
    jobs = ctx.job_svc.list_jobs(
        status=status,
        record_id=record_id,
        affected_record_id=affected_record_id,
        affected_schema=affected_schema,
        offset=offset,
        limit=limit,
    )
    return [WorkflowJobResponse.from_dto(j) for j in jobs]


@router.post("/drain", status_code=202)
def drain_jobs(background_tasks: BackgroundTasks):
    """Kick off the worker to process all pending jobs."""
    background_tasks.add_task(run_pending_jobs)
    return {"status": "draining"}


@router.post("/{job_id}/rerun", response_model=WorkflowJobResponse, status_code=202)
def rerun_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    ctx: AppContext = Depends(get_ctx),
):
    """Enqueue a new job using the same workflow and record as an existing job."""
    try:
        original = ctx.job_svc.get_job(uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(400, detail="Invalid job ID")
    if original is None:
        raise HTTPException(404, detail=f"Job '{job_id}' not found")

    try:
        record = ctx.record_svc.get(str(original.record_id))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))

    job = ctx.job_svc.enqueue_manual(
        original.workflow_name, record, input_data=original.input_data
    )
    ctx.commit()
    background_tasks.add_task(run_pending_jobs)
    return WorkflowJobResponse.from_dto(job)


@router.get("/{job_id}", response_model=WorkflowJobResponse)
def get_job(job_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        job = ctx.job_svc.get_job(uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(400, detail="Invalid job ID")
    if job is None:
        raise HTTPException(404, detail=f"Job '{job_id}' not found")
    return WorkflowJobResponse.from_dto(job)
