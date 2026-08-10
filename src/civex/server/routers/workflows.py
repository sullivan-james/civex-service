from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    UploadFile,
)

from civex.context import AppContext
from civex.domain.exceptions import (
    NotFoundError,
    ValidationError,
    WorkflowValidationError,
)
from civex.server.background import run_pending_jobs
from civex.server.deps import get_ctx
from civex.server.models import (
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
    try:
        ctx.workflow_svc.delete(stem, force=force)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(409, detail=str(e))


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
        declared_inputs = wf_def.inputs or {}
        resolved: dict[str, Any] = {}
        for input_name, input_decl in declared_inputs.items():
            if input_decl.type == "files":
                uploads = form.getlist(input_name)
                refs = []
                for upload in uploads:
                    if isinstance(upload, UploadFile):
                        data = await upload.read()
                        ref = ctx.file_svc.store_bytes(
                            data, upload.filename or "upload"
                        )
                        refs.append(ref.to_dict())
                if refs:
                    resolved[input_name] = refs
        if resolved:
            input_data = {"__input__": resolved}
    else:
        body = await request.json()
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
