from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer
import yaml

from civex import __version__
from civex.cli.utils import cli_load_config, get_ctx
from civex.console import console
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError


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


def dump(
    output: Path = typer.Option(
        Path("civex-dump.yaml"), "--output", "-o", help="Destination file"
    ),
    no_data: bool = typer.Option(
        False, "--no-data", help="Omit records from the export"
    ),
    no_workflows: bool = typer.Option(
        False, "--no-workflows", help="Omit workflows and plugins from the export"
    ),
) -> None:
    """Export all schemas, datasets, records, and workflows to a YAML file."""
    config = cli_load_config()
    ctx = get_ctx()

    # --- schemas ---
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

    # --- datasets + records ---
    datasets_out = []
    records_out = []
    if not no_data:
        for dataset in ctx.dataset_svc.list_all():
            datasets_out.append(
                {
                    "name": dataset.name,
                    "description": dataset.description,
                    "scope": dataset.scope,
                    "schemas": dataset.schemas,
                }
            )
            for record in ctx.record_svc.find(
                dataset.name, schema_name=None, filters=[], limit=100_000
            ):
                rec: dict = {
                    "dataset": dataset.name,
                    "schema": record.schema_name,
                    "data": record.data,
                }
                if record.parent_record_id:
                    rec["parent_record_id"] = str(record.parent_record_id)
                records_out.append(rec)

    # --- workflows ---
    workflows_out = []
    if not no_workflows:
        workflows_dir = config.civex_dir / "workflows"
        if workflows_dir.exists():
            for path in sorted(workflows_dir.glob("*.yaml")) + sorted(
                workflows_dir.glob("*.yml")
            ):
                workflows_out.append(
                    {"filename": path.name, "content": path.read_text()}
                )

    # --- plugins ---
    plugins_out = []
    if not no_workflows:
        plugins_dir = config.civex_dir / "plugins"
        if plugins_dir.exists():
            for path in sorted(plugins_dir.glob("*.py")):
                plugins_out.append({"filename": path.name, "content": path.read_text()})

    dump_doc = {
        "civex_version": __version__,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "schemas": schemas_out,
        "datasets": datasets_out,
        "records": records_out,
        "workflows": workflows_out,
        "plugins": plugins_out,
    }

    output.write_text(
        yaml.dump(
            dump_doc, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
    )

    total_records = len(records_out)
    file_refs = sum(
        1
        for r in records_out
        for v in r["data"].values()
        if isinstance(v, dict) and "sha256" in v
    )
    console.print(f"[success]Exported to {output}[/success]")
    console.print(f"  Schemas    {len(schemas_out)}")
    console.print(f"  Datasets   {len(datasets_out)}")
    console.print(f"  Records    {total_records}")
    console.print(f"  Workflows  {len(workflows_out)}")
    console.print(f"  Plugins    {len(plugins_out)}")
    if file_refs:
        console.print(
            f"  [warning]File references: {file_refs} — copy _civex/objects/ to restore file content.[/warning]"
        )


def restore(
    dump_file: Path = typer.Argument(..., help="Path to a civex-dump.yaml file"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Restore schemas, datasets, records, and workflows from a dump file."""
    if not dump_file.exists():
        console.print(f"[error]File not found: {dump_file}[/error]")
        raise typer.Exit(1)

    doc = yaml.safe_load(dump_file.read_text())

    n_schemas = len(doc.get("schemas", []))
    n_datasets = len(doc.get("datasets", []))
    n_records = len(doc.get("records", []))
    n_workflows = len(doc.get("workflows", []))
    n_plugins = len(doc.get("plugins", []))

    console.print(f"Restoring from [bold]{dump_file}[/bold]")
    console.print(f"  Exported   {doc.get('exported_at', 'unknown')}")
    console.print(f"  Schemas    {n_schemas}")
    console.print(f"  Datasets   {n_datasets}")
    console.print(f"  Records    {n_records}")
    console.print(f"  Workflows  {n_workflows}")
    console.print(f"  Plugins    {n_plugins}")

    if not yes:
        typer.confirm("Proceed?", abort=True)

    config = cli_load_config()
    ctx = get_ctx()

    # --- schemas (parents-first order guaranteed by dump) ---
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
        except AlreadyExistsError:
            console.print(
                f"  [warning]Schema '{s['name']}' already exists — skipped.[/warning]"
            )
            continue

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

    console.print("  Schemas restored.")

    # --- datasets ---
    for d in doc.get("datasets", []):
        try:
            ctx.dataset_svc.create(
                d["name"],
                description=d.get("description"),
                scope=d.get("scope") or "local",
                schemas=d.get("schemas") or [],
            )
            ctx.commit()
        except AlreadyExistsError as e:
            console.print(f"  [warning]Dataset '{d['name']}': {e} — skipped.[/warning]")

    console.print("  Datasets restored.")

    # --- records ---
    file_field_count = 0
    failed = 0
    for r in doc.get("records", []):
        data = r["data"] or {}
        file_field_count += sum(
            1 for v in data.values() if isinstance(v, dict) and "sha256" in v
        )
        try:
            ctx.record_svc.add(
                r["dataset"],
                r["schema"],
                data,
                parent_record_id=r.get("parent_record_id"),
            )
            ctx.commit()
        except (NotFoundError, ValidationError) as e:
            console.print(f"  [warning]Record skipped: {e}[/warning]")
            failed += 1

    restored = n_records - failed
    console.print(f"  Records restored: {restored}/{n_records}.")
    if file_field_count:
        console.print(
            f"  [warning]{file_field_count} file reference(s) restored. "
            f"Copy _civex/objects/ to make file content accessible.[/warning]"
        )

    # --- workflows ---
    workflows_dir = config.civex_dir / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    for wf in doc.get("workflows", []):
        dest = workflows_dir / wf["filename"]
        dest.write_text(wf["content"])

    console.print("  Workflows restored.")

    # --- plugins ---
    plugins_dir = config.civex_dir / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    plugins_restored = 0
    for p in doc.get("plugins", []):
        filename = p["filename"]
        if (
            "/" in filename
            or "\\" in filename
            or filename.startswith(".")
            or not filename.endswith(".py")
        ):
            console.print(
                f"  [warning]Plugin '{filename}': invalid filename — skipped.[/warning]"
            )
            continue
        (plugins_dir / filename).write_text(p["content"])
        plugins_restored += 1

    console.print(f"  Plugins restored: {plugins_restored}/{n_plugins}.")
    console.print("[success]Restore complete.[/success]")
