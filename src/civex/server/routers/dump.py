from __future__ import annotations

from datetime import datetime, timezone

import yaml
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from civex import __version__
from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.downloads import new_temp_path, serve, temp_paths

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
    schemas_out = []
    for schema in ctx.schema_svc.list_all():
        parent_name = None
        if schema.parent_id:
            parent_dto = ctx.schema_svc._repo.get_by_id(schema.parent_id)
            parent_name = parent_dto.name if parent_dto else None
        schemas_out.append(
            {
                "name": schema.name,
                "label": schema.label,
                "description": schema.description,
                "parent": parent_name,
                "fields": [
                    {
                        "name": f.name,
                        "label": f.label,
                        "type": f.dtype,
                        "required": f.required,
                    }
                    for f in schema.fields
                ],
            }
        )
    schemas_out = _sort_schemas(schemas_out)

    datasets_out = [
        {
            "name": d.name,
            "description": d.description,
            "scope": d.scope,
            "schemas": d.schemas,
        }
        for d in ctx.dataset_svc.list_all()
    ]

    from civex.config import load_config

    try:
        config = load_config()
        workflows_out = []
        workflows_dir = config.civex_dir / "workflows"
        if workflows_dir.exists():
            for path in sorted(workflows_dir.glob("*.yaml")) + sorted(
                workflows_dir.glob("*.yml")
            ):
                workflows_out.append(
                    {"filename": path.name, "content": path.read_text(encoding="utf-8")}
                )
    except Exception:
        workflows_out = []

    try:
        config = load_config()
        plugins_out = []
        plugins_dir = config.civex_dir / "plugins"
        if plugins_dir.exists():
            for path in sorted(plugins_dir.glob("*.py")):
                plugins_out.append(
                    {"filename": path.name, "content": path.read_text(encoding="utf-8")}
                )
    except Exception:
        plugins_out = []

    def _yaml(doc) -> str:
        return yaml.dump(
            doc, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

    # Built section by section into a temp file, with records paged out of
    # the DB, so dump size is bounded by disk rather than memory. The
    # concatenated sections are the same YAML mapping (same key order) a
    # single yaml.dump of the whole document would produce.
    with temp_paths() as tmp:
        path = new_temp_path(".yaml")
        tmp.append(path)
        with path.open("w", encoding="utf-8") as out:
            out.write(
                _yaml(
                    {
                        "civex_version": __version__,
                        "exported_at": datetime.now(timezone.utc).isoformat(),
                        "schemas": schemas_out,
                        "datasets": datasets_out,
                    }
                )
            )

            wrote_records = False
            if not no_data:
                for dataset in ctx.dataset_svc.list_all():
                    for page in ctx.record_svc.iter_find(dataset.name):
                        chunk = []
                        for record in page:
                            rec: dict = {
                                "dataset": dataset.name,
                                "schema": record.schema_name,
                                "data": record.data,
                            }
                            if record.parent_record_id:
                                rec["parent_record_id"] = str(record.parent_record_id)
                            chunk.append(rec)
                        if not wrote_records:
                            out.write("records:\n")
                            wrote_records = True
                        out.write(_yaml(chunk))
            if not wrote_records:
                out.write("records: []\n")

            out.write(_yaml({"workflows": workflows_out, "plugins": plugins_out}))

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
            ctx.commit()
            records_restored += 1
        except (NotFoundError, ValidationError, AlreadyExistsError):
            pass

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


def _sort_schemas(schemas: list[dict]) -> list[dict]:
    """Topological sort — parents before children."""
    by_name = {s["name"]: s for s in schemas}
    result: list[dict] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        parent = by_name[name].get("parent")
        if parent and parent in by_name:
            visit(parent)
        result.append(by_name[name])

    for s in schemas:
        visit(s["name"])
    return result
