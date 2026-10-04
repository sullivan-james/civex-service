from __future__ import annotations

import json
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
)
from starlette.datastructures import UploadFile

from civex.context import AppContext
from civex.domain.exceptions import (
    AllVolumesFull,
    NotFoundError,
    ValidationError,
    VolumeUnavailableError,
    WorkflowValidationError,
)
from civex.server.background import run_pending_jobs
from civex.server.deps import get_ctx
from civex.server.models import (
    RunManyRequest,
    RunManyResponse,
    SkippedJob,
    WorkflowDetailResponse,
    WorkflowInputResponse,
    WorkflowJobResponse,
    WorkflowResponse,
    WorkflowSaveRequest,
    WorkflowStepResponse,
    WorkflowTriggerResponse,
)
from civex.workflows.definition import WorkflowDef

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _step_list(wf: WorkflowDef) -> list[WorkflowStepResponse]:
    return [
        WorkflowStepResponse(
            id=s.id,
            plugin=s.plugin,
            config=s.config,
            inputs=s.inputs,
            condition=s.if_,
        )
        for s in wf.steps
    ]


def _triggers(wf: WorkflowDef) -> dict[str, WorkflowTriggerResponse] | None:
    if wf.triggers is None:
        return None
    triggers = {}
    if wf.triggers.record_created:
        triggers["record_created"] = WorkflowTriggerResponse(
            schema_name=wf.triggers.record_created.schema_name,
            fields=wf.triggers.record_created.fields,
        )
    if wf.triggers.record_updated:
        triggers["record_updated"] = WorkflowTriggerResponse(
            schema_name=wf.triggers.record_updated.schema_name,
            fields=wf.triggers.record_updated.fields,
        )
    return triggers or None


@router.get("", response_model=list[WorkflowResponse])
def list_workflows(ctx: AppContext = Depends(get_ctx)):
    return [
        WorkflowResponse(
            name=wf.name,
            description=wf.description,
            steps=len(wf.steps),
            filename=path.name,
            stem=path.stem,
            record_schema=wf.record_schema,
            inputs={
                k: WorkflowInputResponse(
                    type=v.type, label=v.label, description=v.description
                )
                for k, v in (wf.inputs or {}).items()
            }
            or None,
        )
        for path, wf in ctx.workflow_svc.list_defs()
    ]


@router.get("/{stem}", response_model=WorkflowDetailResponse)
def get_workflow(stem: str, ctx: AppContext = Depends(get_ctx)):
    try:
        path, wf, content = ctx.workflow_svc.get(stem)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return WorkflowDetailResponse(
        name=wf.name,
        description=wf.description,
        steps=len(wf.steps),
        filename=path.name,
        stem=path.stem,
        record_schema=wf.record_schema,
        content=content,
        step_list=_step_list(wf),
        triggers=_triggers(wf),
    )


@router.put("/{stem}", response_model=WorkflowDetailResponse)
def save_workflow(
    stem: str, body: WorkflowSaveRequest, ctx: AppContext = Depends(get_ctx)
):
    try:
        path, wf = ctx.workflow_svc.save(stem, body.content)
    except WorkflowValidationError as e:
        raise HTTPException(422, detail=e.errors)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return WorkflowDetailResponse(
        name=wf.name,
        description=wf.description,
        steps=len(wf.steps),
        filename=path.name,
        stem=stem,
        record_schema=wf.record_schema,
        content=body.content,
        step_list=_step_list(wf),
        triggers=_triggers(wf),
    )


@router.delete("/{stem}", status_code=204)
def delete_workflow(stem: str, force: bool = False, ctx: AppContext = Depends(get_ctx)):
    # ValidationError (e.g. workflow still has active jobs, force=False)
    # isn't caught here -- see the matching comment on store.remove_volume:
    # the registered CivexError handler already maps it to 422 consistently.
    try:
        ctx.workflow_svc.delete(stem, force=force)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.post("/{name}/run-many", response_model=RunManyResponse, status_code=202)
def run_workflow_on_many(
    name: str,
    body: RunManyRequest,
    background_tasks: BackgroundTasks,
    ctx: AppContext = Depends(get_ctx),
):
    """Run one workflow on several records: one queued run per record, in one
    request, one commit and one pass of the worker. A record that is missing, or
    is not the schema the workflow is for, is listed under `skipped` with the
    reason and the rest are still queued. A workflow that asks for files cannot
    be run this way (422): the files differ per run. Refused (422) while
    automation is paused."""
    wf_def = ctx.workflow_svc.find_by_name(name)
    if wf_def is None:
        raise HTTPException(404, detail=f"Workflow '{name}' not found")
    if any(i.type == "files" for i in (wf_def.inputs or {}).values()):
        raise HTTPException(
            422,
            detail=f"Workflow '{name}' needs files for each run, so it can't be "
            "run on several records at once.",
        )
    started = []
    skipped = []
    for raw in dict.fromkeys(body.record_ids):
        try:
            record = ctx.record_svc.get(raw)
        except (NotFoundError, ValueError):
            skipped.append(SkippedJob(id=raw, reason="No such record."))
            continue
        if wf_def.record_schema and record.schema_name != wf_def.record_schema:
            skipped.append(
                SkippedJob(
                    id=raw,
                    reason=f"Not a {wf_def.record_schema} record "
                    f"(it is a {record.schema_name}).",
                )
            )
            continue
        started.append(ctx.job_svc.enqueue_manual(name, record))
    ctx.commit()
    if started:
        background_tasks.add_task(run_pending_jobs)
    return RunManyResponse(
        started=[WorkflowJobResponse.from_dto(j) for j in started], skipped=skipped
    )


@router.post("/{name}/run", response_model=WorkflowJobResponse, status_code=202)
async def run_workflow(
    name: str,
    background_tasks: BackgroundTasks,
    request: Request,
    ctx: AppContext = Depends(get_ctx),
):
    wf_def = ctx.workflow_svc.find_by_name(name)
    if wf_def is None:
        raise HTTPException(404, detail=f"Workflow '{name}' not found")

    # Accept both JSON (simple run) and multipart/form-data (batch run with files).
    content_type = request.headers.get("content-type", "")
    input_data: dict[str, Any] | None = None

    if (
        "multipart/form-data" in content_type
        or "application/x-www-form-urlencoded" in content_type
    ):
        form = await request.form()
        record_id = str(form.get("record_id", ""))
        # Files uploaded as run inputs belong to the triggering record's
        # collection, whose home volume (if any) receives new content.
        input_collection: str | None = None
        if record_id:
            try:
                input_collection = str(ctx.record_svc.get(record_id).dataset_id)
            except NotFoundError:
                input_collection = None
        declared_inputs = wf_def.inputs or {}
        resolved: dict[str, Any] = {}
        for input_name, input_decl in declared_inputs.items():
            if input_decl.type == "files":
                uploads = form.getlist(input_name)
                refs = []
                for upload in uploads:
                    if isinstance(upload, UploadFile):
                        data = await upload.read()
                        try:
                            ref = ctx.file_svc.store_bytes(
                                data, upload.filename or "upload", input_collection
                            )
                        except (AllVolumesFull, VolumeUnavailableError) as e:
                            raise HTTPException(507, detail=str(e))
                        refs.append(ref.to_dict())
                if refs:
                    resolved[input_name] = refs
        if resolved:
            input_data = {"__input__": resolved}
    else:
        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            raise HTTPException(422, detail=f"Invalid JSON body: {e}")
        record_id = body.get("record_id", "")

    if not record_id:
        raise HTTPException(422, detail="record_id is required")

    try:
        record = ctx.record_svc.get(record_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))

    if wf_def.record_schema and record.schema_name != wf_def.record_schema:
        raise HTTPException(
            422,
            detail=f"Workflow '{name}' requires a {wf_def.record_schema} record, "
            f"got {record.schema_name}",
        )

    job = ctx.job_svc.enqueue_manual(name, record, input_data=input_data)
    ctx.commit()
    background_tasks.add_task(run_pending_jobs)
    return WorkflowJobResponse.from_dto(job)
