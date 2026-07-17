from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.exceptions import AlreadyExistsError, NotFoundError

app = typer.Typer(help="Manage schemas (data structure definitions)")


@app.command("create")
def schema_create(
    name: str = typer.Argument(...),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
    parent: Optional[str] = typer.Option(
        None, "--parent", "-p", help="Inherit fields from this schema"
    ),
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
        console.print(
            "[info]No schemas yet. Use `civex schema create <name>` to add one.[/info]"
        )
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
            schema.name
            if rf.source_schema_name == schema.name
            else f"↑ {rf.source_schema_name}",
        )
    console.print(table)


@app.command("add-field")
def schema_add_field(
    schema_name: str = typer.Argument(...),
    field_name: str = typer.Argument(...),
    dtype: str = typer.Option(..., "--type", "-t"),
    required: bool = typer.Option(False, "--required/--optional"),
    # reference
    references: Optional[str] = typer.Option(
        None, "--references", help="Target schema (--type reference)"
    ),
    # integer / float
    min_val: Optional[float] = typer.Option(
        None, "--min", help="Minimum value (integer/float)"
    ),
    max_val: Optional[float] = typer.Option(
        None, "--max", help="Maximum value (integer/float)"
    ),
    # string
    choices: Optional[str] = typer.Option(
        None, "--choices", help="Comma-separated allowed values (string)"
    ),
    max_length: Optional[int] = typer.Option(
        None, "--max-length", help="Maximum character length (string)"
    ),
    # file / file_list
    accept: Optional[str] = typer.Option(
        None, "--accept", help="Allowed extensions e.g. '.csv,.txt' (file/file_list)"
    ),
    max_size: Optional[int] = typer.Option(
        None, "--max-size", help="Maximum file size in bytes (file/file_list)"
    ),
) -> None:
    """Add a field to a schema.

    Restriction examples:
      --type integer --min 0 --max 100
      --type string --choices "left,right,bilateral"
      --type string --max-length 255
      --type file --accept ".csv,.txt" --max-size 10485760
    """
    restrictions: dict = {}

    if dtype == "reference":
        if not references:
            console.print(
                "[error]--references SCHEMA is required when --type is reference.[/error]"
            )
            raise typer.Exit(1)
        restrictions["schema"] = references
    elif references:
        console.print("[error]--references is only valid for --type reference.[/error]")
        raise typer.Exit(1)

    if dtype in ("integer", "float"):
        if min_val is not None:
            restrictions["min"] = int(min_val) if dtype == "integer" else min_val
        if max_val is not None:
            restrictions["max"] = int(max_val) if dtype == "integer" else max_val
    elif min_val is not None or max_val is not None:
        console.print(
            "[error]--min/--max are only valid for --type integer or float.[/error]"
        )
        raise typer.Exit(1)

    if dtype == "string":
        if choices:
            restrictions["choices"] = [
                c.strip() for c in choices.split(",") if c.strip()
            ]
        if max_length is not None:
            restrictions["max_length"] = max_length
    elif choices or max_length is not None:
        console.print(
            "[error]--choices/--max-length are only valid for --type string.[/error]"
        )
        raise typer.Exit(1)

    if dtype in ("file", "file_list"):
        if accept:
            restrictions["accept"] = accept
        if max_size is not None:
            restrictions["max_size"] = max_size
    elif accept or max_size is not None:
        console.print(
            "[error]--accept/--max-size are only valid for --type file or file_list.[/error]"
        )
        raise typer.Exit(1)

    ctx = _ctx()
    try:
        field = ctx.schema_svc.add_field(
            schema_name,
            field_name,
            dtype,
            required=required,
            restrictions=restrictions or None,
        )
        ctx.commit()
        req = " (required)" if field.required else ""
        ref = f" → {references}" if dtype == "reference" else ""
        restr = f" {field.restrictions}" if field.restrictions else ""
        console.print(
            f"[success]Added '{field.name}' ({field.dtype}{ref}{req}){restr} to schema '{schema_name}'.[/success]"
        )
    except (NotFoundError, AlreadyExistsError, ValueError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("update")
def schema_update(
    name: str = typer.Argument(...),
    rename: Optional[str] = typer.Option(
        None, "--rename", help="New name for the schema"
    ),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
    display_field: Optional[str] = typer.Option(
        None, "--display-field", help="Field name to use as the record's natural name"
    ),
    clear_display_field: bool = typer.Option(
        False, "--clear-display-field", help="Remove the display field (revert to auto)"
    ),
) -> None:
    """Update a schema's name, description, or display field."""
    if (
        rename is None
        and description is None
        and display_field is None
        and not clear_display_field
    ):
        console.print(
            "[error]Provide at least one of --rename, --description, --display-field, or --clear-display-field.[/error]"
        )
        raise typer.Exit(1)
    df = ...
    if display_field is not None:
        df = display_field
    elif clear_display_field:
        df = None
    ctx = _ctx()
    try:
        schema = ctx.schema_svc.update(
            name, new_name=rename, description=description, display_field=df
        )
        ctx.commit()
        console.print(f"[success]Updated schema '{schema.name}'.[/success]")
    except (NotFoundError, AlreadyExistsError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("update-field")
def schema_update_field(
    schema_name: str = typer.Argument(...),
    field_name: str = typer.Argument(...),
    rename: Optional[str] = typer.Option(
        None, "--rename", help="New name for the field"
    ),
    required: Optional[bool] = typer.Option(
        None, "--required/--optional", help="Set required/optional"
    ),
    # integer / float
    min_val: Optional[float] = typer.Option(
        None, "--min", help="Minimum value (integer/float)"
    ),
    max_val: Optional[float] = typer.Option(
        None, "--max", help="Maximum value (integer/float)"
    ),
    # string
    choices: Optional[str] = typer.Option(
        None, "--choices", help="Comma-separated allowed values (string)"
    ),
    max_length: Optional[int] = typer.Option(
        None, "--max-length", help="Maximum character length (string)"
    ),
    # file / file_list
    accept: Optional[str] = typer.Option(
        None, "--accept", help="Allowed extensions e.g. '.csv,.txt'"
    ),
    max_size: Optional[int] = typer.Option(
        None, "--max-size", help="Maximum file size in bytes"
    ),
    clear_restrictions: bool = typer.Option(
        False, "--clear-restrictions", help="Remove all restrictions"
    ),
) -> None:
    """Update a field's name, required flag, or restrictions."""
    has_restriction_flags = any(
        v is not None for v in [min_val, max_val, choices, max_length, accept, max_size]
    )

    if (
        rename is None
        and required is None
        and not has_restriction_flags
        and not clear_restrictions
    ):
        console.print(
            "[error]Provide at least one of: --rename, --required/--optional, restriction flags, --clear-restrictions.[/error]"
        )
        raise typer.Exit(1)

    ctx = _ctx()
    try:
        # Look up field to get its dtype for restriction building
        schema = ctx.schema_svc.get(schema_name)
        field = next((f for f in schema.fields if f.name == field_name), None)
        if field is None:
            from civex.domain.exceptions import NotFoundError as _NF

            raise _NF(f"Field '{field_name}' not found on schema '{schema_name}'")

        # Warn if making required but existing records are missing this field.
        if required:
            all_datasets = ctx.dataset_svc.list_all()
            affected = []
            for d in all_datasets:
                missing = [
                    r
                    for r in ctx.record_svc.find(
                        d.name, schema_name=schema_name, filters=[], limit=100_000
                    )
                    if field_name not in r.data
                ]
                if missing:
                    affected.append((d.name, len(missing)))
            if affected:
                for dataset_name, count in affected:
                    console.print(
                        f"[warning]{count} record(s) in '{dataset_name}' are missing '{field_name}'.[/warning]"
                    )
                typer.confirm("Make field required anyway?", abort=True)

        # Build restrictions dict
        new_restrictions: dict | None = None
        if clear_restrictions:
            new_restrictions = {}
        elif has_restriction_flags:
            new_restrictions = dict(field.restrictions or {})
            dtype = field.dtype
            if dtype in ("integer", "float"):
                if min_val is not None:
                    new_restrictions["min"] = (
                        int(min_val) if dtype == "integer" else min_val
                    )
                if max_val is not None:
                    new_restrictions["max"] = (
                        int(max_val) if dtype == "integer" else max_val
                    )
            if dtype == "string":
                if choices:
                    new_restrictions["choices"] = [
                        c.strip() for c in choices.split(",") if c.strip()
                    ]
                if max_length is not None:
                    new_restrictions["max_length"] = max_length
            if dtype in ("file", "file_list"):
                if accept:
                    new_restrictions["accept"] = accept
                if max_size is not None:
                    new_restrictions["max_size"] = max_size

        updated = ctx.schema_svc.update_field(
            schema_name,
            field_name,
            new_name=rename,
            required=required,
            restrictions=new_restrictions,
        )
        ctx.commit()
        parts = [f"'{updated.name}'"]
        parts.append("required" if updated.required else "optional")
        if updated.restrictions:
            parts.append(str(updated.restrictions))
        console.print(f"[success]Updated field: {' · '.join(parts)}[/success]")
    except (NotFoundError, AlreadyExistsError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("remove-field")
def schema_remove_field(
    schema_name: str = typer.Argument(...),
    field_name: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Remove a field from a schema."""
    if not yes:
        typer.confirm(
            f"Remove field '{field_name}' from schema '{schema_name}'?", abort=True
        )
    ctx = _ctx()
    try:
        ctx.schema_svc.delete_field(schema_name, field_name)
        ctx.commit()
        console.print(
            f"[success]Removed field '{field_name}' from '{schema_name}'.[/success]"
        )
    except NotFoundError as e:
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
