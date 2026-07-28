from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from civex.cli.utils import drain_jobs, get_ctx as _ctx
from civex.console import console
from civex.domain.dtos import FileRef
from civex.domain.exceptions import CoercionError, NotFoundError, ValidationError

app = typer.Typer(help="Manage records")


@app.command("add")
def record_add(
    dataset_name: str = typer.Option(..., "--to", help="Dataset to add the record to"),
    schema_name: str = typer.Option(
        ..., "--schema", "-s", help="Schema for this record"
    ),
) -> None:
    """Add a record, prompting for each field defined on the schema."""
    ctx = _ctx()
    try:
        dataset = ctx.dataset_svc.get(dataset_name)
        schema = ctx.schema_svc.get(schema_name)
        fields = ctx.record_svc.get_resolved_fields(schema_name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    # Prompt for parent record ID if this is a child schema.
    parent_record_id: str | None = None
    if schema.parent_id:
        parent_schema = ctx.schema_svc._repo.get_by_id(schema.parent_id)
        parent_schema_name = parent_schema.name if parent_schema else "unknown"
        while True:
            raw_id = typer.prompt(f"  Parent record ID ({parent_schema_name})")
            try:
                parent_record = ctx.record_svc.get(raw_id)
                if parent_record.dataset_id != dataset.id:
                    console.print(
                        f"[error]  Parent record must be in dataset '{dataset_name}'.[/error]"
                    )
                    continue
                console.print(f"  [dim]↑ {parent_schema_name} record[/dim]")
                parent_record_id = raw_id
                break
            except NotFoundError:
                console.print(
                    f"[error]  Record '{raw_id}' not found — try again.[/error]"
                )

    if not fields:
        console.print("[warning]Schema has no own fields.[/warning]")

    data: dict = {}
    for rf in fields:
        dtype_label = rf.field.dtype
        if rf.field.dtype == "reference" and rf.field.restrictions.get("schema"):
            dtype_label = f"reference → {rf.field.restrictions['schema']}"
        label = f"  {rf.field.name} ({dtype_label})"
        if rf.field.required:
            label += " [required]"

        while True:
            raw = typer.prompt(label, default="" if not rf.field.required else ...)
            if raw == "" and not rf.field.required:
                break
            try:
                data[rf.field.name] = ctx.record_svc.coerce_value(
                    raw, rf.field.dtype, rf.field.name, rf.field.restrictions
                )
                break
            except CoercionError as e:
                console.print(f"[error]  {e}[/error]")

    try:
        record = ctx.record_svc.add(
            dataset_name, schema_name, data, parent_record_id=parent_record_id
        )
        ctx.commit()
        console.print(f"[success]Added record {record.id}.[/success]")
        drain_jobs(ctx)
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("show")
def record_show(record_id: str = typer.Argument(...)) -> None:
    """Show a record's field values."""
    ctx = _ctx()
    try:
        record = ctx.record_svc.get(record_id)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    console.print(f"[bold]Record {record.id}[/bold]")
    console.print(f"  Schema    {record.schema_name}")
    console.print(f"  Dataset   {record.dataset_id}")
    if record.parent_record_id:
        console.print(f"  Parent    {record.parent_record_id}")
    console.print(f"  Created   {record.created_at.strftime('%Y-%m-%d %H:%M UTC')}")

    if record.data:
        table = Table("Field", "Value")
        for k, v in record.data.items():
            if isinstance(v, dict) and "sha256" in v:
                ref = FileRef.from_dict(v)
                display = (
                    f"{ref.filename} ({ref.size} bytes, sha256:{ref.sha256[:12]}…)"
                )
            else:
                display = str(v)
            table.add_row(k, display)
        console.print(table)
    else:
        console.print("  (no field values)")


@app.command("update")
def record_update(record_id: str = typer.Argument(...)) -> None:
    """Update a record's field values, prompting for each field."""
    ctx = _ctx()
    try:
        record = ctx.record_svc.get(record_id)
        fields = ctx.record_svc.get_resolved_fields(record.schema_name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    data = dict(record.data)
    for rf in fields:
        current = data.get(rf.field.name, "")
        dtype_label = rf.field.dtype
        if rf.field.dtype == "reference" and rf.field.restrictions.get("schema"):
            dtype_label = f"reference → {rf.field.restrictions['schema']}"
        label = f"  {rf.field.name} ({dtype_label})"
        if rf.field.required:
            label += " [required]"

        while True:
            raw = typer.prompt(f"{label} [current: {current}]", default=str(current))
            if raw == "" and not rf.field.required:
                data.pop(rf.field.name, None)
                break
            try:
                data[rf.field.name] = ctx.record_svc.coerce_value(
                    raw, rf.field.dtype, rf.field.name, rf.field.restrictions
                )
                break
            except CoercionError as e:
                console.print(f"[error]  {e}[/error]")

    ctx.record_svc.update(record_id, data)
    ctx.commit()
    console.print(f"[success]Updated record {record.id}.[/success]")
    drain_jobs(ctx)


@app.command("find")
def record_find(
    dataset_name: str = typer.Option(..., "--in"),
    schema_name: Optional[str] = typer.Option(
        None, "--schema", "-s", help="Filter by schema"
    ),
    where: Optional[list[str]] = typer.Option(
        None, "--where", help="field=value filter (repeatable)"
    ),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """List records in a dataset. Use --schema to filter by type and show field columns."""
    ctx = _ctx()
    try:
        records = ctx.record_svc.find(
            dataset_name, schema_name=schema_name, filters=where or [], limit=limit
        )
    except (NotFoundError, ValueError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    if not records:
        console.print("[info]No records match.[/info]")
        return

    if schema_name:
        fields = ctx.record_svc.get_resolved_fields(schema_name)
        field_names = [rf.field.name for rf in fields]
        table = Table("ID", *field_names, "Created")
        for r in records:
            row_vals = []
            for f in field_names:
                v = r.data.get(f, "")
                if isinstance(v, dict) and "sha256" in v:
                    row_vals.append(FileRef.from_dict(v).filename)
                else:
                    row_vals.append(str(v))
            table.add_row(
                str(r.id)[:8] + "…", *row_vals, r.created_at.strftime("%Y-%m-%d")
            )
    else:
        table = Table("ID", "Schema", "Created")
        for r in records:
            table.add_row(
                str(r.id)[:8] + "…", r.schema_name, r.created_at.strftime("%Y-%m-%d")
            )

    console.print(table)


@app.command("delete")
def record_delete(
    record_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Clear any reference/reference_list fields pointing at this record "
        "instead of blocking the delete",
    ),
) -> None:
    """Delete a record."""
    if not yes:
        typer.confirm(f"Delete record '{record_id}'?", abort=True)
    ctx = _ctx()
    try:
        ctx.record_svc.delete(record_id, force=force)
        ctx.commit()
        console.print(f"[success]Deleted record '{record_id}'.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("delete-all")
def record_delete_all(
    dataset_name: str = typer.Argument(..., help="Dataset to delete records from"),
    schema: Optional[str] = typer.Option(
        None, "--schema", "-s", help="Limit to this schema"
    ),
    yes: bool = typer.Option(False, "--yes", "-y"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Clear any reference/reference_list fields pointing at deleted records "
        "instead of blocking the delete",
    ),
) -> None:
    """Delete all records in a dataset (optionally filtered by schema)."""
    target = f"all '{schema}' records" if schema else "ALL records"
    if not yes:
        typer.confirm(f"Delete {target} in dataset '{dataset_name}'?", abort=True)
    ctx = _ctx()
    try:
        deleted = ctx.record_svc.delete_all(
            dataset_name, schema_name=schema, force=force
        )
        ctx.commit()
        console.print(
            f"[success]Deleted {deleted} record(s) from '{dataset_name}'.[/success]"
        )
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
