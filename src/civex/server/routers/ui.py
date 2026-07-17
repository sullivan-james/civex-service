from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.server.background import run_pending_jobs as _run_pending_jobs
from civex.server.deps import get_ctx
from civex.workflows.definition import load_workflow

router = APIRouter(prefix="/ui", include_in_schema=False)

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _r(url: str, flash_ok: str = "", flash_error: str = "") -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    if flash_ok:
        url += f"{sep}flash_ok={flash_ok}"
    elif flash_error:
        url += f"{sep}flash_error={flash_error}"
    return RedirectResponse(url, status_code=303)


def _tmpl(request: Request, name: str, **ctx):
    flash_ok = request.query_params.get("flash_ok", "")
    flash_error = request.query_params.get("flash_error", "")
    return _templates.TemplateResponse(
        request, name, {"flash_ok": flash_ok, "flash_error": flash_error, **ctx}
    )


# --- Dashboard ---


@router.get("")
def index(request: Request, ctx: AppContext = Depends(get_ctx)):
    schemas = ctx.schema_svc.list_all()
    datasets = ctx.dataset_svc.list_all()
    record_count = sum(d.record_count for d in datasets)
    try:
        from civex.config import load_config

        wf_dir = load_config().civex_dir / "workflows"
        workflow_count = (
            len(list(wf_dir.glob("*.yaml")) + list(wf_dir.glob("*.yml")))
            if wf_dir.exists()
            else 0
        )
    except Exception:
        workflow_count = 0
    return _tmpl(
        request,
        "index.html",
        schema_count=len(schemas),
        dataset_count=len(datasets),
        record_count=record_count,
        workflow_count=workflow_count,
    )


# --- Schemas ---


@router.get("/schemas")
def schemas_list(request: Request, ctx: AppContext = Depends(get_ctx)):
    raw = ctx.schema_svc.list_all()
    schemas = []
    for s in raw:
        parent_name = None
        if s.parent_id:
            p = ctx.schema_svc._repo.get_by_id(s.parent_id)
            parent_name = p.name if p else None
        all_fields = ctx.schema_svc.collect_fields(s)
        schemas.append(
            {
                "name": s.name,
                "description": s.description,
                "parent_name": parent_name,
                "field_count": len(all_fields),
            }
        )
    return _tmpl(request, "schemas.html", schemas=schemas)


@router.post("/schemas")
def schemas_create(
    request: Request,
    name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    parent: Annotated[str, Form()] = "",
    ctx: AppContext = Depends(get_ctx),
):
    try:
        ctx.schema_svc.create(
            name, description=description or None, parent=parent or None
        )
    except (AlreadyExistsError, NotFoundError) as e:
        return _r("/ui/schemas", flash_error=str(e))
    return _r(f"/ui/schemas/{name}", flash_ok=f"Schema '{name}' created.")


@router.get("/schemas/{name}")
def schema_detail(name: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    try:
        schema = ctx.schema_svc.get(name)
    except NotFoundError:
        return _r("/ui/schemas", flash_error=f"Schema '{name}' not found.")
    parent_name = None
    if schema.parent_id:
        p = ctx.schema_svc._repo.get_by_id(schema.parent_id)
        parent_name = p.name if p else None
    resolved = ctx.schema_svc.collect_fields(schema)
    fields = [
        {
            "field": {
                "name": rf.field.name,
                "type": rf.field.dtype,
                "required": rf.field.required,
            },
            "source": rf.source_schema_name,
        }
        for rf in resolved
    ]
    datasets = [d for d in ctx.dataset_svc.list_all() if d.schema_name == name]
    return _tmpl(
        request,
        "schema_detail.html",
        schema=schema,
        parent_name=parent_name,
        fields=fields,
        datasets=datasets,
    )


@router.post("/schemas/{name}/fields")
def schema_add_field(
    name: str,
    field_name: Annotated[str, Form(alias="name")],
    field_type: Annotated[str, Form(alias="type")],
    required: Annotated[str, Form()] = "",
    ctx: AppContext = Depends(get_ctx),
):
    try:
        ctx.schema_svc.add_field(name, field_name, field_type, required=bool(required))
    except (NotFoundError, AlreadyExistsError, ValueError) as e:
        return _r(f"/ui/schemas/{name}", flash_error=str(e))
    return _r(f"/ui/schemas/{name}", flash_ok=f"Field '{field_name}' added.")


@router.post("/schemas/{name}/delete")
def schema_delete(name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.schema_svc.delete(name)
    except NotFoundError as e:
        return _r("/ui/schemas", flash_error=str(e))
    return _r("/ui/schemas", flash_ok=f"Schema '{name}' deleted.")


# --- Datasets ---


@router.get("/datasets")
def datasets_list(request: Request, ctx: AppContext = Depends(get_ctx)):
    return _tmpl(
        request,
        "datasets.html",
        datasets=ctx.dataset_svc.list_all(),
        schemas=ctx.schema_svc.list_all(),
    )


@router.post("/datasets")
def datasets_create(
    name: Annotated[str, Form()],
    schema_name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    ctx: AppContext = Depends(get_ctx),
):
    try:
        ctx.dataset_svc.create(
            name, schema_name=schema_name, description=description or None
        )
    except (AlreadyExistsError, NotFoundError) as e:
        return _r("/ui/datasets", flash_error=str(e))
    return _r(f"/ui/datasets/{name}", flash_ok=f"Dataset '{name}' created.")


@router.get("/datasets/{name}")
def dataset_detail(name: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    try:
        dataset = ctx.dataset_svc.get(name)
    except NotFoundError:
        return _r("/ui/datasets", flash_error=f"Dataset '{name}' not found.")
    schema = ctx.schema_svc.get(dataset.schema_name)
    resolved = ctx.schema_svc.collect_fields(schema)
    fields = [
        {
            "field": {
                "name": rf.field.name,
                "type": rf.field.dtype,
                "required": rf.field.required,
            },
            "source": rf.source_schema_name,
        }
        for rf in resolved
    ]
    field_names = [rf.field.name for rf in resolved]
    records = ctx.record_svc.find(name, filters=[], limit=200)
    return _tmpl(
        request,
        "dataset_detail.html",
        dataset=dataset,
        fields=fields,
        field_names=field_names,
        records=records,
    )


@router.post("/datasets/{name}/records")
async def dataset_add_record(
    name: str,
    request: Request,
    ctx: AppContext = Depends(get_ctx),
):
    form = await request.form()
    dataset = ctx.dataset_svc.get(name)
    schema = ctx.schema_svc.get(dataset.schema_name)
    resolved = ctx.schema_svc.collect_fields(schema)

    data: dict[str, Any] = {}
    for rf in resolved:
        raw = form.get(rf.field.name, "")
        if raw == "":
            continue
        dtype = rf.field.dtype
        if dtype == "file":
            try:
                data[rf.field.name] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        elif dtype == "integer":
            data[rf.field.name] = int(raw)
        elif dtype == "float":
            data[rf.field.name] = float(raw)
        elif dtype == "boolean":
            data[rf.field.name] = raw.lower() in ("true", "on", "1", "yes")
        else:
            data[rf.field.name] = raw

    try:
        ctx.record_svc.add(name, data)
    except (NotFoundError, ValidationError) as e:
        return _r(f"/ui/datasets/{name}", flash_error=str(e))
    return _r(f"/ui/datasets/{name}", flash_ok="Record added.")


@router.post("/datasets/{name}/delete")
def dataset_delete(name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.dataset_svc.delete(name)
    except NotFoundError as e:
        return _r("/ui/datasets", flash_error=str(e))
    return _r("/ui/datasets", flash_ok=f"Dataset '{name}' deleted.")


# --- Records ---


@router.get("/records/{record_id}")
def record_detail(record_id: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    try:
        record = ctx.record_svc.get(record_id)
    except NotFoundError:
        return _r("/ui/datasets", flash_error=f"Record '{record_id}' not found.")
    dataset = ctx.dataset_svc._datasets.get_by_id(record.dataset_id)
    dataset_name = dataset.name if dataset else "unknown"
    try:
        fields = ctx.record_svc.get_resolved_fields(record.schema_name)
    except Exception:
        fields = []
    return _tmpl(
        request,
        "record_detail.html",
        record=record,
        dataset_name=dataset_name,
        fields=fields,
    )


@router.post("/records/{record_id}/update")
async def record_update(
    record_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: AppContext = Depends(get_ctx),
):
    try:
        record = ctx.record_svc.get(record_id)
    except NotFoundError as e:
        return _r("/ui/datasets", flash_error=str(e))

    fields = ctx.record_svc.get_resolved_fields(record.schema_name)
    form = await request.form()
    data = dict(record.data)

    for rf in fields:
        raw = form.get(rf.field.name)
        if raw is None:
            continue
        dtype = rf.field.dtype
        if dtype == "file":
            if raw and raw not in ("", "null"):
                try:
                    data[rf.field.name] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    pass
        elif raw == "":
            data.pop(rf.field.name, None)
        elif dtype == "integer":
            try:
                data[rf.field.name] = int(raw)
            except ValueError:
                pass
        elif dtype == "float":
            try:
                data[rf.field.name] = float(raw)
            except ValueError:
                pass
        elif dtype == "boolean":
            data[rf.field.name] = raw.lower() in ("true", "on", "1", "yes")
        else:
            data[rf.field.name] = raw

    try:
        ctx.record_svc.update(record_id, data)
        ctx.commit()
    except (NotFoundError, ValidationError) as e:
        return _r(f"/ui/records/{record_id}", flash_error=str(e))
    background_tasks.add_task(_run_pending_jobs)
    return _r(f"/ui/records/{record_id}", flash_ok="Record updated.")


@router.post("/records/{record_id}/delete")
def record_delete(record_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        record = ctx.record_svc.get(record_id)
        dataset = ctx.dataset_svc._datasets.get_by_id(record.dataset_id)
        dataset_name = dataset.name if dataset else None
        ctx.record_svc.delete(record_id)
    except NotFoundError as e:
        return _r("/ui/datasets", flash_error=str(e))
    dest = f"/ui/datasets/{dataset_name}" if dataset_name else "/ui/datasets"
    return _r(dest, flash_ok="Record deleted.")


# --- Workflows ---


@router.get("/workflows")
def workflows_list(request: Request):
    workflows = []
    try:
        from civex.config import load_config

        config = load_config()
        wf_dir = config.civex_dir / "workflows"
        if wf_dir.exists():
            for path in sorted(wf_dir.glob("*.yaml")) + sorted(wf_dir.glob("*.yml")):
                try:
                    wf = load_workflow(path)
                    workflows.append(
                        {
                            "name": wf.name,
                            "description": wf.description,
                            "steps": len(wf.steps),
                            "filename": path.name,
                        }
                    )
                except Exception:
                    pass
    except Exception:
        pass
    return _tmpl(request, "workflows.html", workflows=workflows)


@router.post("/workflows/{name}/run")
def workflow_run(
    name: str,
    record_id: Annotated[str, Form()],
    background_tasks: BackgroundTasks,
    ctx: AppContext = Depends(get_ctx),
):
    try:
        record = ctx.record_svc.get(record_id)
    except NotFoundError as e:
        return _r("/ui/workflows", flash_error=str(e))

    job = ctx.job_svc.enqueue_manual(name, record)
    ctx.commit()
    background_tasks.add_task(_run_pending_jobs)
    return _r("/ui/jobs", flash_ok=f"Workflow '{name}' queued — job {str(job.id)[:8]}…")


# --- Jobs ---


@router.get("/jobs")
def jobs_list(request: Request, ctx: AppContext = Depends(get_ctx)):
    jobs = ctx.job_svc.list_jobs()
    has_active = any(j.status in ("pending", "running") for j in jobs)
    return _tmpl(request, "jobs.html", jobs=jobs, has_active=has_active)


@router.get("/jobs/partial")
def jobs_partial(request: Request, ctx: AppContext = Depends(get_ctx)):
    jobs = ctx.job_svc.list_jobs()
    has_active = any(j.status in ("pending", "running") for j in jobs)
    return _templates.TemplateResponse(
        request, "_jobs_table.html", {"jobs": jobs, "has_active": has_active}
    )
