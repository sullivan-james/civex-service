from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from civex.config import load_config
from civex.console import console
from civex.context import build_local_context
from civex.domain.exceptions import AlreadyExistsError, CivexError, NotFoundError

app = typer.Typer(help="Manage schemas (data structure definitions)")


def _ctx():
    return build_local_context(load_config())


@app.command("create")
def schema_create(
    name: str = typer.Argument(...),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
    parent: Optional[str] = typer.Option(None, "--parent", "-p", help="Inherit fields from this schema"),
) -> None:
    """Define a new schema."""
    ctx = _ctx()
    try:
        schema = ctx.schema_svc.create(name, description=description, parent=parent)
        ctx.commit()
        console.print(f"[success]Created schema '{schema.name}'.[/success]")
    except (AlreadyExistsError, NotFoundError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("list")
def schema_list() -> None:
    """List all schemas."""
    ctx = _ctx()
    schemas = ctx.schema_svc.list_all()
    if not schemas:
        console.print("[info]No schemas yet. Use `civex schema create <name>` to add one.[/info]")
        return

    table = Table("Name", "Parent", "Fields", "Description")
    for s in schemas:
        parent_name = "-"
        if s.parent_id:
            parent_dto = ctx.schema_svc._repo.get_by_id(s.parent_id)
            parent_name = parent_dto.name if parent_dto else "-"
        all_fields = ctx.schema_svc.collect_fields(s)
        table.add_row(s.name, parent_name, str(len(all_fields)), s.description or "")
    console.print(table)


@app.command("show")
def schema_show(name: str = typer.Argument(...)) -> None:
    """Inspect a schema's fields (including inherited)."""
    ctx = _ctx()
    try:
        schema = ctx.schema_svc.get(name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    console.print(f"[bold]{schema.name}[/bold]")
    if schema.description:
        console.print(f"  {schema.description}")
    if schema.parent_id:
        parent = ctx.schema_svc._repo.get_by_id(schema.parent_id)
        if parent:
            console.print(f"  Inherits: {parent.name}")

    fields = ctx.schema_svc.collect_fields(schema)
    if not fields:
        console.print("  No fields defined.")
        return

    table = Table("Field", "Type", "Required", "Source")
    for rf in fields:
        table.add_row(
            rf.field.name,
            rf.field.dtype,
            "yes" if rf.field.required else "",
            schema.name if rf.source_schema_name == schema.name else f"↑ {rf.source_schema_name}",
        )
    console.print(table)


@app.command("add-field")
def schema_add_field(
    schema_name: str = typer.Argument(...),
    field_name: str = typer.Argument(...),
    dtype: str = typer.Option(..., "--type", "-t"),
    required: bool = typer.Option(False, "--required/--optional"),
) -> None:
    """Add a field to a schema."""
    ctx = _ctx()
    try:
        field = ctx.schema_svc.add_field(schema_name, field_name, dtype, required=required)
        ctx.commit()
        req = " (required)" if field.required else ""
        console.print(f"[success]Added '{field.name}' ({field.dtype}{req}) to schema '{schema_name}'.[/success]")
    except (NotFoundError, AlreadyExistsError, ValueError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("delete")
def schema_delete(
    name: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a schema and its fields."""
    if not yes:
        typer.confirm(f"Delete schema '{name}'?", abort=True)
    ctx = _ctx()
    try:
        ctx.schema_svc.delete(name)
        ctx.commit()
        console.print(f"[success]Deleted '{name}'.[/success]")
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
