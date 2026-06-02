from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from civex.config import load_config
from civex.console import console
from civex.context import build_local_context
from civex.domain.dtos import FileRef
from civex.domain.exceptions import CoercionError, NotFoundError, ValidationError

app = typer.Typer(help="Manage records")


def _ctx():
    return build_local_context(load_config())


@app.command("add")
def record_add(
    dataset_name: str = typer.Option(..., "--to", help="Dataset to add the record to"),
) -> None:
    """Add a record, prompting for each field defined on the schema."""
    ctx = _ctx()
    try:
        fields = ctx.record_svc.get_resolved_fields(dataset_name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    if not fields:
        console.print("[warning]Schema has no fields — record will be empty.[/warning]")

    data: dict = {}
    for rf in fields:
        label = f"  {rf.field.name} ({rf.field.dtype})"
        if rf.field.required:
            label += " [required]"

        while True:
            raw = typer.prompt(label, default="" if not rf.field.required else ...)
            if raw == "" and not rf.field.required:
                break
            try:
                data[rf.field.name] = ctx.record_svc.coerce_value(raw, rf.field.dtype, rf.field.name)
                break
            except CoercionError as e:
                console.print(f"[error]  {e}[/error]")

    try:
        record = ctx.record_svc.add(dataset_name, data)
        ctx.commit()
        console.print(f"[success]Added record {record.id}.[/success]")
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
    console.print(f"  Dataset   {record.dataset_id}")
    console.print(f"  Created   {record.created_at.strftime('%Y-%m-%d %H:%M UTC')}")

    if record.data:
        table = Table("Field", "Value")
        for k, v in record.data.items():
            # Display FileRef dicts more readably
            if isinstance(v, dict) and "sha256" in v:
                ref = FileRef.from_dict(v)
                display = f"{ref.filename} ({ref.size} bytes, sha256:{ref.sha256[:12]}…)"
            else:
                display = str(v)
            table.add_row(k, display)
        console.print(table)
    else:
        console.print("  (no field values)")


@app.command("update")
def record_update(
    record_id: str = typer.Argument(...),
) -> None:
    """Update a record's field values, prompting for each field."""
    ctx = _ctx()
    try:
        record = ctx.record_svc.get(record_id)
        dataset = ctx.dataset_svc._datasets.get_by_id(record.dataset_id)
        fields = ctx.record_svc.get_resolved_fields(dataset.name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    data = dict(record.data)
    for rf in fields:
        current = data.get(rf.field.name, "")
        label = f"  {rf.field.name} ({rf.field.dtype})"
        if rf.field.required:
            label += " [required]"

        while True:
            raw = typer.prompt(f"{label} [current: {current}]", default=str(current))
            if raw == "" and not rf.field.required:
                data.pop(rf.field.name, None)
                break
            try:
                data[rf.field.name] = ctx.record_svc.coerce_value(raw, rf.field.dtype, rf.field.name)
                break
            except CoercionError as e:
                console.print(f"[error]  {e}[/error]")

    ctx.record_svc.update(record_id, data)
    ctx.commit()
    console.print(f"[success]Updated record {record.id}.[/success]")


@app.command("find")
def record_find(
    dataset_name: str = typer.Option(..., "--in"),
    where: Optional[list[str]] = typer.Option(
        None, "--where", help="field=value filter (repeatable)"
    ),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """Filter records in a dataset. Example: --where subject=S01 --where condition=A"""
    ctx = _ctx()
    try:
        records = ctx.record_svc.find(dataset_name, filters=where or [], limit=limit)
        fields = ctx.record_svc.get_resolved_fields(dataset_name)
    except (NotFoundError, ValueError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    if not records:
        console.print("[info]No records match.[/info]")
        return

    field_names = [rf.field.name for rf in fields]
    if not field_names and records:
        field_names = list(records[0].data.keys())

    table = Table("ID", *field_names, "Created")
    for r in records:
        row_vals = []
        for f in field_names:
            v = r.data.get(f, "")
            if isinstance(v, dict) and "sha256" in v:
                row_vals.append(FileRef.from_dict(v).filename)
            else:
                row_vals.append(str(v))
        table.add_row(str(r.id)[:8] + "…", *row_vals, r.created_at.strftime("%Y-%m-%d"))
    console.print(table)


@app.command("delete")
def record_delete(
    record_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a record."""
    if not yes:
        typer.confirm(f"Delete record '{record_id}'?", abort=True)
    ctx = _ctx()
    try:
        ctx.record_svc.delete(record_id)
        ctx.commit()
        console.print(f"[success]Deleted record '{record_id}'.[/success]")
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
