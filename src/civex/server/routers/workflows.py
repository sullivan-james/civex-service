from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from civex.context import AppContext
from civex.domain.exceptions import ConfigError, NotFoundError
from civex.server.background import run_pending_jobs
from civex.server.deps import get_ctx
from civex.server.models import (
    WorkflowDetailResponse,
    WorkflowJobResponse,
    WorkflowResponse,
    WorkflowSaveRequest,
)
from civex.workflows.definition import load_workflow
from civex.config import load_config

router = APIRouter(prefix="/workflows", tags=["workflows"])

_SAFE_STEM = re.compile(r'^[\w-]+$')


def _list_workflow_defs():
    try:
        config = load_config()
    except ConfigError:
        return []
    workflows_dir = config.civex_dir / "workflows"
    if not workflows_dir.exists():
        return []
    results = []
    for path in sorted(workflows_dir.glob("*.yaml")) + sorted(workflows_dir.glob("*.yml")):
        try:
            results.append((path, load_workflow(path)))
        except Exception:
            continue
    return results


def _find_path(stem: str):
    """Return the Path for a workflow stem, or None if not found."""
    try:
        config = load_config()
    except ConfigError:
        return None
    for ext in ("yaml", "yml"):
        p = config.civex_dir / "workflows" / f"{stem}.{ext}"
        if p.exists():
            return p
    return None


@router.get("", response_model=list[WorkflowResponse])
def list_workflows():
    return [
        WorkflowResponse(
            name=wf.name,
            description=wf.description,
            steps=len(wf.steps),
            filename=path.name,
            stem=path.stem,
            record_schema=wf.record_schema,
            inputs={k: {"type": v.type, "label": v.label, "description": v.description}
                    for k, v in (wf.inputs or {}).items()} or None,
        )
        for path, wf in _list_workflow_defs()
    ]


@router.get("/{stem}", response_model=WorkflowDetailResponse)
def get_workflow(stem: str):
    path = _find_path(stem)
    if path is None:
        raise HTTPException(404, detail=f"Workflow '{stem}' not found")
    content = path.read_text()
    try:
        wf = load_workflow(path)
    except Exception as e:
        raise HTTPException(422, detail=f"Invalid workflow YAML: {e}")
    return WorkflowDetailResponse(name=wf.name, description=wf.description,
                                   steps=len(wf.steps), filename=path.name,
                                   stem=path.stem, content=content)


@router.put("/{stem}", response_model=WorkflowDetailResponse)
def save_workflow(stem: str, body: WorkflowSaveRequest):
    if not _SAFE_STEM.match(stem):
        raise HTTPException(400, detail="Stem must contain only letters, numbers, hyphens, and underscores")
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(500, detail=str(e))

    # Validate YAML before writing
    try:
        import yaml as _yaml
        raw = _yaml.safe_load(body.content)
        from civex.workflows.definition import WorkflowDef
        wf = WorkflowDef.model_validate(raw)
    except Exception as e:
        raise HTTPException(422, detail=f"Invalid workflow YAML: {e}")

    path = config.civex_dir / "workflows" / f"{stem}.yaml"
    path.write_text(body.content, encoding="utf-8")

    return WorkflowDetailResponse(name=wf.name, description=wf.description,
                                   steps=len(wf.steps), filename=path.name,
                                   stem=stem, content=body.content)


@router.delete("/{stem}", status_code=204)
def delete_workflow(stem: str):
    path = _find_path(stem)
    if path is None:
        raise HTTPException(404, detail=f"Workflow '{stem}' not found")
    path.unlink()


@router.post("/{name}/run", response_model=WorkflowJobResponse, status_code=202)
async def run_workflow(
    name: str,
    background_tasks: BackgroundTasks,
    request: Request,
    ctx: AppContext = Depends(get_ctx),
):
    wf_def = next(
        (wf for path, wf in _list_workflow_defs() if wf.name == name or path.stem == name),
        None,
    )
    if wf_def is None:
        raise HTTPException(404, detail=f"Workflow '{name}' not found")

    # Accept both JSON (simple run) and multipart/form-data (batch run with files).
    content_type = request.headers.get("content-type", "")
    input_data: dict[str, Any] | None = None

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        record_id = str(form.get("record_id", ""))
        declared_inputs = wf_def.inputs or {}
        resolved: dict[str, Any] = {}
        for input_name, input_decl in declared_inputs.items():
            if input_decl.type == "files":
                uploads = form.getlist(input_name)
                refs = []
                for upload in uploads:
                    if hasattr(upload, "read"):
                        data = await upload.read()
                        ref = ctx.file_svc.store_bytes(data, upload.filename or "upload")
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
