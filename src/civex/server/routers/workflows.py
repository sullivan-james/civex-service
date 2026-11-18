from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
)
from starlette.datastructures import UploadFile

from civex.context import AppContext, context_factory
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
    WorkflowEnabledRequest,
    WorkflowSaveRequest,
    TrialOnRecord,
    WorkflowTrialManyRequest,
    WorkflowTrialManyResponse,
    WorkflowTrialRequest,
    WorkflowTrialResponse,
    WorkflowStepResponse,
    WorkflowTriggerResponse,
)
from civex.workflows.definition import WorkflowDef, trigger_summaries
from civex.workflows.trial import try_workflow

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


def _inputs(wf: WorkflowDef) -> dict[str, WorkflowInputResponse] | None:
    return {
        k: WorkflowInputResponse(type=v.type, label=v.label, description=v.description)
        for k, v in (wf.inputs or {}).items()
    } or None


def _detail(stem: str, filename: str, wf: WorkflowDef, content: str):
    return WorkflowDetailResponse(
        name=wf.name,
        description=wf.description,
        steps=len(wf.steps),
        filename=filename,
        stem=stem,
        record_schema=wf.record_schema,
        inputs=_inputs(wf),
        enabled=wf.enabled,
        content=content,
        step_list=_step_list(wf),
        triggers=_triggers(wf),
    )


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
            inputs=_inputs(wf),
            enabled=wf.enabled,
            runs_on=trigger_summaries(wf),
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
    return _detail(path.stem, path.name, wf, content)


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
    return _detail(stem, path.name, wf, body.content)


@router.patch("/{stem}", response_model=WorkflowDetailResponse)
def set_workflow_enabled(
    stem: str, body: WorkflowEnabledRequest, ctx: AppContext = Depends(get_ctx)
):
    """Switch a workflow on (its triggers start runs) or off (it runs only when
    someone starts or tries it). Only the file's `enabled:` line changes. 422
    when the workflow no longer passes its checks."""
    try:
        path, wf, content = ctx.workflow_svc.set_enabled(stem, body.enabled)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except WorkflowValidationError as e:
        raise HTTPException(422, detail=e.errors)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return _detail(stem, path.name, wf, content)


@router.delete("/{stem}", status_code=204)
def delete_workflow(stem: str, force: bool = False, ctx: AppContext = Depends(get_ctx)):
    # ValidationError (e.g. workflow still has active jobs, force=False)
    # isn't caught here -- see the matching comment on store.remove_volume:
    # the registered CivexError handler already maps it to 422 consistently.
    try:
        ctx.workflow_svc.delete(stem, force=force)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


async def _form_inputs(
    form: Any, wf_def: WorkflowDef, record_id: str, ctx: AppContext
) -> dict[str, Any] | None:
    """The files a form carries for each declared `files` input, stored, as
    the `__input__` outputs a run starts with (None when there are none)."""
    # Files uploaded as run inputs belong to the triggering record's
    # collection, whose home volume (if any) receives new content.
    input_collection: str | None = None
    if record_id:
        try:
            input_collection = str(ctx.record_svc.get(record_id).dataset_id)
        except NotFoundError:
            input_collection = None
    resolved: dict[str, Any] = {}
    for input_name, input_decl in (wf_def.inputs or {}).items():
        if input_decl.type != "files":
            continue
        refs = []
        for upload in form.getlist(input_name):
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
    return {"__input__": resolved} if resolved else None


@router.post("/try", response_model=WorkflowTrialResponse)
async def try_workflow_on_record(request: Request, ctx: AppContext = Depends(get_ctx)):
    """Try a workflow (saved or not: the YAML is sent) on one record without
    keeping anything: it runs as a real run would, inside a transaction that is
    always rolled back, and the answer says what it would have done (each
    record created, changed or deleted, with the values before and after, and
    the runs its saves would start). JSON `{content, record_id}`, or a form
    with those plus the files for each `files` input. Works whether the
    workflow is on or off, and while automation is paused. 422 when the YAML
    doesn't pass its checks or the record isn't the kind it runs on; a step
    that fails is not an error but `ok: false` with `error`."""
    content_type = request.headers.get("content-type", "")
    form = None
    if "multipart/form-data" in content_type:
        form = await request.form()
        content = str(form.get("content", ""))
        record_id = str(form.get("record_id", ""))
    else:
        try:
            body = WorkflowTrialRequest.model_validate(await request.json())
        except (json.JSONDecodeError, PydanticValidationError) as e:
            raise HTTPException(422, detail=f"Invalid request: {e}")
        content, record_id = body.content, body.record_id
    if not record_id:
        raise HTTPException(422, detail="Choose a record to try it on.")
    try:
        wf_def = ctx.workflow_svc.check(content)
    except WorkflowValidationError as e:
        raise HTTPException(422, detail=e.errors)
    input_data = (
        await _form_inputs(form, wf_def, record_id, ctx) if form is not None else None
    )
    try:
        result = try_workflow(ctx, wf_def, record_id, input_data)
    finally:
        # Nothing of a trial stays, not even the files it was given.
        ctx.rollback()
    return WorkflowTrialResponse.model_validate(result.to_dict())


@router.post("/try-many", response_model=WorkflowTrialManyResponse)
async def try_workflow_on_records(request: Request, ctx: AppContext = Depends(get_ctx)):
    """Try a workflow on several records at once, keeping nothing: each is
    tried as `POST /workflows/try` would, one after the other, and all of it is
    rolled back. Names no records and it takes the most recently changed
    records of the kind the workflow runs on (`sample`, 5 by default), so an
    editor can show what a change would do without anyone choosing. JSON
    `{content, record_ids, sample}`, or a form with those (`record_ids`
    repeated) plus the files for each `files` input, given to every trial. A
    record it can't run on is answered with `problem`, not an error."""
    content_type = request.headers.get("content-type", "")
    form = None
    if "multipart/form-data" in content_type:
        form = await request.form()
        raw = {
            "content": str(form.get("content", "")),
            "record_ids": [str(v) for v in form.getlist("record_ids") if v],
            "sample": int(str(form.get("sample") or 5)),
        }
    else:
        try:
            raw = await request.json()
        except json.JSONDecodeError as e:
            raise HTTPException(422, detail=f"Invalid request: {e}")
    try:
        body = WorkflowTrialManyRequest.model_validate(raw)
    except PydanticValidationError as e:
        raise HTTPException(422, detail=f"Invalid request: {e}")
    try:
        wf_def = ctx.workflow_svc.check(body.content)
    except WorkflowValidationError as e:
        raise HTTPException(422, detail=e.errors)
    sampled = not body.record_ids
    if sampled:
        if not wf_def.record_schema:
            raise HTTPException(
                422, detail="Choose the kind of record it runs on to try it."
            )
        ids: list[str] = [
            str(r.id)
            for r in ctx.record_svc.recently_changed(wf_def.record_schema, body.sample)
        ]
    else:
        ids = body.record_ids
    trials: list[TrialOnRecord] = []
    try:
        input_data = (
            await _form_inputs(form, wf_def, ids[0] if ids else "", ctx)
            if form is not None
            else None
        )
        for record_id in ids:
            try:
                record = ctx.record_svc.get(record_id)
            except NotFoundError:
                trials.append(
                    TrialOnRecord(record_id=record_id, problem="No such record.")
                )
                continue
            try:
                result = try_workflow(ctx, wf_def, str(record.id), input_data)
            except (ValidationError, NotFoundError) as e:
                trials.append(
                    TrialOnRecord(
                        record_id=str(record.id),
                        name=record.natural_name,
                        problem=str(e),
                    )
                )
                continue
            trials.append(
                TrialOnRecord(
                    record_id=str(record.id),
                    name=record.natural_name,
                    result=WorkflowTrialResponse.model_validate(result.to_dict()),
                )
            )
    finally:
        ctx.rollback()
    return WorkflowTrialManyResponse(trials=trials, sampled=sampled)


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
        background_tasks.add_task(run_pending_jobs, context_factory(ctx.project))
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
        input_data = await _form_inputs(form, wf_def, record_id, ctx)
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
    background_tasks.add_task(run_pending_jobs, context_factory(ctx.project))
    return WorkflowJobResponse.from_dto(job)
