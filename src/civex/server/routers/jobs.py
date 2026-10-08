from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError
from civex.server.background import run_pending_jobs
from civex.server.deps import get_ctx
from civex.domain.run_filters import RUN_FIELDS
from civex.server.models import (
    AutomationStatusResponse,
    DeleteJobsRequest,
    DeleteJobsResponse,
    FailureGroupResponse,
    RunFieldResponse,
    RerunJobsRequest,
    RerunJobsResponse,
    SkippedJob,
    WorkflowJobResponse,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])
automation_router = APIRouter(prefix="/automation", tags=["jobs"])


def _state(ctx: AppContext, cancelled: int = 0) -> AutomationStatusResponse:
    return AutomationStatusResponse(
        **ctx.job_svc.automation_state(), cancelled=cancelled
    )


@automation_router.get("", response_model=AutomationStatusResponse)
def automation_status(ctx: AppContext = Depends(get_ctx)):
    """Whether automation is paused, and how many runs are waiting or running."""
    return _state(ctx)


@automation_router.post("/stop", response_model=AutomationStatusResponse)
def stop_automation(ctx: AppContext = Depends(get_ctx)):
    """Stop all automation, for example a workflow that keeps triggering itself.

    Pauses automation (nothing new is triggered or started, and manual runs are
    refused), cancels every waiting run, and stops every running one before its
    next step. A step already in progress finishes or times out first. Call
    `POST /automation/resume` to start again.
    """
    cancelled = ctx.job_svc.stop_all()
    ctx.commit()
    return _state(ctx, cancelled)


@automation_router.post("/resume", response_model=AutomationStatusResponse)
def resume_automation(
    background_tasks: BackgroundTasks, ctx: AppContext = Depends(get_ctx)
):
    """Lift a pause. Triggers fire and queued runs are picked up again."""
    ctx.job_svc.resume()
    background_tasks.add_task(run_pending_jobs)
    return _state(ctx)


@router.get("/filter-fields", response_model=list[RunFieldResponse])
def run_filter_fields(ctx: AppContext = Depends(get_ctx)):
    """The fields a run filter may test, with their types and operators."""
    return [
        RunFieldResponse(
            name=f.name,
            label=f.label,
            type=f.type,
            description=f.description,
            choices=f.choices,
            operators=f.operators,
        )
        for f in RUN_FIELDS
    ]


@router.get("/failure-groups", response_model=list[FailureGroupResponse])
def failure_groups(
    filter: str | None = Query(
        default=None,
        description='A filter tree as JSON (`{"and": [{"field": "status", '
        '"op": "eq", "value": "failed"}]}`), the same shape as the records '
        "filter. Fields come from GET /jobs/filter-fields.",
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Failed runs grouped by workflow and what went wrong, most first, so a
    thousand failures read as the few causes they are. `filter` narrows which
    runs are counted (only failed ones ever are)."""
    return ctx.job_svc.failure_groups(filter)


@router.get("/count")
def count_jobs(
    status: str | None = None,
    record_id: str | None = None,
    affected_record_id: str | None = None,
    affected_schema: str | None = None,
    trigger: str | None = None,
    search: str | None = None,
    workflow: str | None = None,
    filter: str | None = Query(
        default=None,
        description='A filter tree as JSON (`{"and": [{"field": "status", '
        '"op": "eq", "value": "failed"}]}`), the same shape as the records '
        "filter. Fields come from GET /jobs/filter-fields.",
    ),
    ctx: AppContext = Depends(get_ctx),
):
    return {
        "total": ctx.job_svc.count_jobs(
            workflow=workflow,
            status=status,
            record_id=record_id,
            affected_record_id=affected_record_id,
            affected_schema=affected_schema,
            trigger=trigger,
            search=search,
            where=filter,
        )
    }


@router.get("", response_model=list[WorkflowJobResponse])
def list_jobs(
    status: str | None = None,
    record_id: str | None = None,
    affected_record_id: str | None = None,
    affected_schema: str | None = None,
    trigger: str | None = None,
    workflow: str | None = Query(
        default=None, description="Only runs of the workflow with exactly this name."
    ),
    search: str | None = Query(
        default=None, description="Match on workflow name or error text."
    ),
    filter: str | None = Query(
        default=None,
        description='A filter tree as JSON (`{"and": [{"field": "status", '
        '"op": "eq", "value": "failed"}]}`), the same shape as the records '
        "filter. Fields come from GET /jobs/filter-fields.",
    ),
    sort: str | None = Query(
        default=None,
        description="'column[:asc|desc]' over workflow_name, status, trigger, "
        "schema_name, created_at. Newest first otherwise.",
    ),
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
        workflow=workflow,
        status=status,
        record_id=record_id,
        affected_record_id=affected_record_id,
        affected_schema=affected_schema,
        offset=offset,
        limit=limit,
        trigger=trigger,
        search=search,
        sort=sort,
        where=filter,
    )
    return [WorkflowJobResponse.from_dto(j) for j in jobs]


@router.post("/{job_id}/cancel", response_model=WorkflowJobResponse)
def cancel_job(job_id: str, ctx: AppContext = Depends(get_ctx)):
    """Cancel one run. A waiting run never starts; a running one stops before
    its next step (a step already in progress finishes or times out first). A
    run that has already finished is returned unchanged."""
    try:
        job = ctx.job_svc.cancel_job(uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(400, detail="Invalid job ID")
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    ctx.commit()
    return WorkflowJobResponse.from_dto(job)


@router.post("/rerun", response_model=RerunJobsResponse, status_code=202)
def rerun_jobs(
    body: RerunJobsRequest,
    background_tasks: BackgroundTasks,
    ctx: AppContext = Depends(get_ctx),
):
    """Repeat several runs at once: each is queued as a new run of the same
    workflow on the same record, with the same input. One request, one commit and
    one pass of the worker, however many. A run that cannot be repeated (a bad id,
    an unknown run, a record that has since been deleted) is listed under
    `skipped` with the reason, and the rest are still queued. Refused (422) while
    automation is paused."""
    if (body.ids is None) == (body.filter is None and not body.search):
        raise HTTPException(422, detail="Give either ids, or a filter or search.")
    ids = (
        body.ids
        if body.ids is not None
        else [str(i) for i in ctx.job_svc.run_ids(body.filter, search=body.search)]
    )
    started = []
    skipped = []
    for raw in dict.fromkeys(ids):
        try:
            original = ctx.job_svc.get_job(uuid.UUID(raw))
        except ValueError:
            skipped.append(SkippedJob(id=raw, reason="Not a run id."))
            continue
        if original is None:
            skipped.append(SkippedJob(id=raw, reason="No such run."))
            continue
        try:
            record = ctx.record_svc.get(str(original.record_id))
        except NotFoundError:
            skipped.append(SkippedJob(id=raw, reason="Its record no longer exists."))
            continue
        started.append(
            ctx.job_svc.enqueue_manual(
                original.workflow_name, record, input_data=original.input_data
            )
        )
    ctx.commit()
    if started:
        background_tasks.add_task(run_pending_jobs)
    return RerunJobsResponse(
        started=[WorkflowJobResponse.from_dto(j) for j in started], skipped=skipped
    )


@router.post("/drain", status_code=202)
def drain_jobs(background_tasks: BackgroundTasks):
    """Kick off the worker to process all pending jobs."""
    background_tasks.add_task(run_pending_jobs)
    return {"status": "draining"}


@router.post("/delete", response_model=DeleteJobsResponse)
def delete_jobs(body: DeleteJobsRequest, ctx: AppContext = Depends(get_ctx)):
    """Delete runs, whatever their state. A waiting run never starts; a running
    one stops before its next step; a finished one is removed with its step
    log. What a run already changed in records stays (and is in their history).
    Which: `ids`, or every run the list shows for `filter` and/or `search`, or
    every run with `every`."""
    narrowed = body.filter is not None or bool(body.search)
    if (body.ids is not None) == (narrowed or body.every):
        raise HTTPException(
            422, detail="Give either ids, or a filter, a search or every."
        )
    if body.ids is not None:
        try:
            ids = [uuid.UUID(i) for i in body.ids]
        except ValueError:
            raise HTTPException(422, detail="Not a run id.")
    else:
        # Every run the list shows for this filter and search, however many.
        ids = ctx.job_svc.run_ids(body.filter, limit=None, search=body.search)
    deleted = ctx.job_svc.delete_runs(ids)
    ctx.commit()
    return DeleteJobsResponse(deleted=deleted)


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: str, ctx: AppContext = Depends(get_ctx)):
    """Delete one run, whatever its state (see POST /jobs/delete)."""
    try:
        run = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid job ID")
    if not ctx.job_svc.delete_runs([run]):
        raise HTTPException(404, detail=f"Job '{job_id}' not found")
    ctx.commit()


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
