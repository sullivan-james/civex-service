from __future__ import annotations


import yaml
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.downloads import new_temp_path, serve, temp_paths
from civex.services.dump_service import RESTORE_BATCH, write_dump

router = APIRouter(tags=["dump"])


class RestoreResult(BaseModel):
    schemas: int
    datasets: int
    records_restored: int
    records_total: int
    workflows: int
    plugins: int


@router.get("/dump")
def export_dump(
    no_data: bool = False,
    ctx: AppContext = Depends(get_ctx),
):
    """Export all schemas, datasets, records, and workflows as a YAML file download."""
    from civex.config import load_config

    try:
        civex_dir = load_config().civex_dir
    except Exception:
        civex_dir = None

    # Written section by section into a temp file with records paged out of
    # the DB (see dump_service), so dump size is bounded by disk, not memory.
    with temp_paths() as tmp:
        path = new_temp_path(".yaml")
        tmp.append(path)
        with path.open("w", encoding="utf-8") as out:
            write_dump(
                out,
                ctx.schema_svc,
                ctx.dataset_svc,
                ctx.record_svc,
                civex_dir,
                include_data=not no_data,
            )
        tmp.remove(path)
        return serve(path, "application/yaml", "civex-dump.yaml")


@router.post("/restore", response_model=RestoreResult)
async def import_dump(
    file: UploadFile = File(...),
    ctx: AppContext = Depends(get_ctx),
):
    """Restore schemas, datasets, records, and workflows from an uploaded YAML dump."""
    raw = await file.read()
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    if not isinstance(doc, dict):
        raise HTTPException(status_code=400, detail="Dump file must be a YAML mapping")

    schemas_restored = 0
    for s in doc.get("schemas", []):
        try:
            ctx.schema_svc.create(
                s["name"],
                description=s.get("description"),
                parent=s.get("parent"),
                label=s.get("label"),
                # A dump predating slug validation must restore as-is; see
                # SchemaService.create.
                allow_legacy_name=True,
            )
            ctx.commit()
            schemas_restored += 1
        except AlreadyExistsError:
            pass

        for f in s.get("fields", []):
            try:
                ctx.schema_svc.add_field(
                    s["name"],
                    f["name"],
                    f["type"],
                    required=f.get("required", False),
                    label=f.get("label"),
                    allow_legacy_name=True,
                )
                ctx.commit()
            except AlreadyExistsError:
                pass

    datasets_restored = 0
    for d in doc.get("datasets", []):
        try:
            ctx.dataset_svc.create(
                d["name"],
                description=d.get("description"),
                scope=d.get("scope") or "local",
                schemas=d.get("schemas") or [],
            )
            ctx.commit()
            datasets_restored += 1
        except AlreadyExistsError:
            pass

    records_total = len(doc.get("records", []))
    records_restored = 0
    for r in doc.get("records", []):
        try:
            ctx.record_svc.add(
                r["dataset"],
                r["schema"],
                r.get("data") or {},
                parent_record_id=r.get("parent_record_id"),
            )
            records_restored += 1
            if records_restored % RESTORE_BATCH == 0:
                ctx.commit()
        except (NotFoundError, ValidationError, AlreadyExistsError):
            pass
    ctx.commit()

    from civex.config import load_config

    config = load_config()

    workflows_restored = 0
    workflows_dir = config.civex_dir / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    for wf in doc.get("workflows", []):
        (workflows_dir / wf["filename"]).write_text(wf["content"], encoding="utf-8")
        workflows_restored += 1

    plugins_restored = 0
    plugins_dir = config.civex_dir / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    for p in doc.get("plugins", []):
        filename = p["filename"]
        if (
            "/" in filename
            or "\\" in filename
            or filename.startswith(".")
            or not filename.endswith(".py")
        ):
            continue
        (plugins_dir / filename).write_text(p["content"], encoding="utf-8")
        plugins_restored += 1
    if plugins_restored:
        from civex.plugins.registry import discover_user_plugins

        discover_user_plugins(plugins_dir)

    return RestoreResult(
        schemas=schemas_restored,
        datasets=datasets_restored,
        records_restored=records_restored,
        records_total=records_total,
        workflows=workflows_restored,
        plugins=plugins_restored,
    )
