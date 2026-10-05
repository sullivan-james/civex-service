from __future__ import annotations

from typing import Any, Optional

import typer
from rich.table import Table

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.domain.query import RecordQuery

app = typer.Typer(help="Manage schemas (data structure definitions)")


@app.command("create")
def schema_create(
    name: str = typer.Argument(
        ...,
        help="Schema name — the machine key used by workflows and CSV headers "
        "(lowercase, underscores, e.g. acoustic_recording)",
    ),
    label: Optional[str] = typer.Option(
        None,
        "--label",
        "-l",
        help="Human-facing display name, free text (e.g. 'Acoustic Recording')",
    ),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Schema description"
    ),
    parent: Optional[str] = typer.Option(
        None, "--parent", "-p", help="Inherit fields from this schema"
    ),
) -> None:
    """Define a new schema.

    The name is a slug because workflow YAML, CSV headers and display fields
    all reference it as text. Put spaces and capitals in --label instead —
    that is what the UI and CLI show, and it can be changed freely.
    """
    ctx = _ctx()
    try:
        schema = ctx.schema_svc.create(
            name, description=description, parent=parent, label=label
        )
        ctx.commit()
        console.print(f"[success]Created schema '{schema.name}'.[/success]")
    except (AlreadyExistsError, NotFoundError, ValidationError) as e:
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

    table = Table("Label", "Name", "Parent", "Fields", "Description")
    for s in schemas:
        parent_name = "-"
        if s.parent_id:
            parent_dto = ctx.schema_svc._repo.get_by_id(s.parent_id)
            parent_name = parent_dto.name if parent_dto else "-"
        all_fields = ctx.schema_svc.collect_fields(s)
        table.add_row(
            s.display_name,
            s.name,
            parent_name,
            str(len(all_fields)),
            s.description or "",
        )
    console.print(table)


@app.command("show")
def schema_show(name: str = typer.Argument(..., help="Schema name")) -> None:
    """Inspect a schema's fields (including inherited)."""
    ctx = _ctx()
    try:
        schema = ctx.schema_svc.get(name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    console.print(f"[bold]{schema.display_name}[/bold] ([dim]{schema.name}[/dim])")
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

    table = Table("Label", "Field", "Type", "Required", "Source")
    for rf in fields:
        table.add_row(
            rf.field.display_name,
            rf.field.name,
            rf.field.dtype,
            "yes" if rf.field.required else "",
            schema.name
            if rf.source_schema_name == schema.name
            else f"↑ {rf.source_schema_name}",
        )
    console.print(table)
    for key in schema.unique_key_names:
        console.print(f"  Unique: {', '.join(key)}")


def _unique_fields_arg() -> Any:
    return typer.Argument(..., help="The fields of the key (the schema's own)")


@app.command("unique")
def schema_unique(name: str = typer.Argument(..., help="Schema name")) -> None:
    """List a schema's uniqueness keys."""
    ctx = _ctx()
    try:
        keys = ctx.schema_svc.get(name).unique_key_names
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    if not keys:
        console.print(f"Schema '{name}' has no uniqueness keys.")
        return
    for key in keys:
        console.print(f"  unique: {', '.join(key)}")


@app.command("add-unique")
def schema_add_unique(
    name: str = typer.Argument(..., help="Schema name"),
    fields: list[str] = _unique_fields_arg(),
) -> None:
    """Require a combination of fields to be unique.

    No two records of the schema may then hold the same values in all of the
    given fields, within the same parent record (or the same collection, for
    a top-level record). A record with a blank in any of them is not
    constrained. Refused while existing records already share values.
    """
    ctx = _ctx()
    try:
        current = ctx.schema_svc.get(name).unique_key_names
        ctx.schema_svc.set_unique_keys(name, [*current, fields])
        ctx.commit()
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    console.print(
        f"[success]'{name}' records must now have a unique ({', '.join(fields)}).[/success]"
    )


@app.command("remove-unique")
def schema_remove_unique(
    name: str = typer.Argument(..., help="Schema name"),
    fields: list[str] = _unique_fields_arg(),
) -> None:
    """Remove a uniqueness key (give the same fields it was added with)."""
    ctx = _ctx()
    try:
        current = ctx.schema_svc.get(name).unique_key_names
        remaining = [k for k in current if set(k) != set(fields)]
        if len(remaining) == len(current):
            console.print(
                f"[error]'{name}' has no uniqueness key on ({', '.join(fields)}).[/error]"
            )
            raise typer.Exit(1)
        ctx.schema_svc.set_unique_keys(name, remaining)
        ctx.commit()
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    console.print(f"[success]Removed the unique ({', '.join(fields)}).[/success]")


def _parse_bbox(text: str) -> list[float]:
    try:
        parts = [float(x) for x in text.split(",")]
    except ValueError:
        parts = []
    if len(parts) != 4:
        console.print("[error]--bbox must be WEST,SOUTH,EAST,NORTH in degrees.[/error]")
        raise typer.Exit(1)
    return parts


def _typed_restrictions(
    dtype: str,
    unit: Optional[str],
    precision: Optional[str],
    geometry_types: Optional[str],
    bbox: Optional[str],
) -> dict:
    """Restrictions for the float/date/geo flags, rejecting a flag used on the
    wrong type the way the older flags do."""
    out: dict = {}
    for flag, value, types, key in (
        ("--unit", unit, ("float",), "unit"),
        ("--precision", precision, ("date",), "precision"),
        ("--geometry-types", geometry_types, ("geo",), "geometry_types"),
        ("--bbox", bbox, ("geo",), "bbox"),
    ):
        if value is None:
            continue
        if dtype not in types:
            console.print(
                f"[error]{flag} is only valid for --type {' or '.join(types)}.[/error]"
            )
            raise typer.Exit(1)
        if key == "geometry_types":
            out[key] = [t.strip() for t in value.split(",") if t.strip()]
        elif key == "bbox":
            out[key] = _parse_bbox(value)
        else:
            out[key] = value
    return out


@app.command("add-field")
def schema_add_field(
    schema_name: str = typer.Argument(..., help="Schema to add the field to"),
    field_name: str = typer.Argument(
        ...,
        help="Field name — the machine key used by workflows and CSV headers "
        "(lowercase, underscores, e.g. recording_date)",
    ),
    label: Optional[str] = typer.Option(
        None,
        "--label",
        "-l",
        help="Human-facing display name, free text (e.g. 'Recording Date')",
    ),
    dtype: str = typer.Option(
        ...,
        "--type",
        "-t",
        help="Field type: integer | float | string | boolean | date | datetime | geo | file | file_list | reference",
    ),
    required: bool = typer.Option(
        False, "--required/--optional", help="Whether the field is required"
    ),
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
    # float
    unit: Optional[str] = typer.Option(
        None,
        "--unit",
        help="Unit every value is stored in, e.g. m or degC (float). Values are "
        "never converted after the fact.",
    ),
    # date
    precision: Optional[str] = typer.Option(
        None,
        "--precision",
        help="Least precise date accepted: year | month | day (date)",
    ),
    # geo
    geometry_types: Optional[str] = typer.Option(
        None,
        "--geometry-types",
        help="Comma-separated shapes allowed, e.g. Point,Polygon (geo)",
    ),
    bbox: Optional[str] = typer.Option(
        None,
        "--bbox",
        help="Allowed area as WEST,SOUTH,EAST,NORTH in degrees; west greater "
        "than east crosses the 180th meridian (geo)",
    ),
) -> None:
    """Add a field to a schema.

    The field name is a slug because workflow steps reference it by name
    (e.g. civex.get_field's field:). Use --label for the human-readable
    version shown in the UI and in `civex schema show`.

    Restriction examples:
      --type integer --min 0 --max 100
      --type string --choices "left,right,bilateral"
      --type string --max-length 255
      --type file --accept ".csv,.txt" --max-size 10485760
      --type float --unit m --min 0
      --type date --precision month
      --type geo --geometry-types Point --bbox "-12,48,4,62"
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
    elif dtype == "longtext":
        if choices:
            console.print("[error]--choices is only valid for --type string.[/error]")
            raise typer.Exit(1)
        if max_length is not None:
            restrictions["max_length"] = max_length
    elif choices or max_length is not None:
        console.print(
            "[error]--choices/--max-length are only valid for --type string"
            " (--max-length also for longtext).[/error]"
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

    restrictions.update(
        _typed_restrictions(dtype, unit, precision, geometry_types, bbox)
    )

    ctx = _ctx()
    try:
        field = ctx.schema_svc.add_field(
            schema_name,
            field_name,
            dtype,
            required=required,
            restrictions=restrictions or None,
            label=label,
        )
        ctx.commit()
        req = " (required)" if field.required else ""
        ref = f" → {references}" if dtype == "reference" else ""
        restr = f" {field.restrictions}" if field.restrictions else ""
        console.print(
            f"[success]Added '{field.name}' ({field.dtype}{ref}{req}){restr} to schema '{schema_name}'.[/success]"
        )
    except (NotFoundError, AlreadyExistsError, ValidationError, ValueError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("update")
def schema_update(
    name: str = typer.Argument(..., help="Schema name"),
    rename: Optional[str] = typer.Option(
        None, "--rename", help="New name (slug) for the schema"
    ),
    label: Optional[str] = typer.Option(
        None,
        "--label",
        "-l",
        help="New display name for the schema; pass '' to clear it",
    ),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="New description for the schema"
    ),
    display_template: Optional[str] = typer.Option(
        None,
        "--display-template",
        help="Template that names the schema's records, e.g. '{site}-{taken_on:YYYY-MM}'. "
        "Fields go in braces; formats follow a colon.",
    ),
    clear_display_template: bool = typer.Option(
        False,
        "--clear-display-template",
        help="Remove the record name template (revert to auto)",
    ),
) -> None:
    """Update a schema's name, label, description, or record name template."""
    if (
        rename is None
        and label is None
        and description is None
        and display_template is None
        and not clear_display_template
    ):
        console.print(
            "[error]Provide at least one of --rename, --label, --description, --display-template, or --clear-display-template.[/error]"
        )
        raise typer.Exit(1)
    tpl: Any = ...
    if display_template is not None:
        tpl = display_template
    elif clear_display_template:
        tpl = None
    ctx = _ctx()
    try:
        schema = ctx.schema_svc.update(
            name,
            new_name=rename,
            description=description,
            display_template=tpl,
            label=... if label is None else label,
        )
        ctx.commit()
        console.print(f"[success]Updated schema '{schema.name}'.[/success]")
    except (NotFoundError, AlreadyExistsError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("update-field")
def schema_update_field(
    schema_name: str = typer.Argument(..., help="Schema containing the field"),
    field_name: str = typer.Argument(..., help="Field name"),
    rename: Optional[str] = typer.Option(
        None, "--rename", help="New name (slug) for the field"
    ),
    label: Optional[str] = typer.Option(
        None,
        "--label",
        "-l",
        help="New display name for the field; pass '' to clear it",
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
    # float
    unit: Optional[str] = typer.Option(
        None,
        "--unit",
        help="Unit every value is stored in, e.g. m or degC (float). Values are "
        "never converted after the fact.",
    ),
    # date
    precision: Optional[str] = typer.Option(
        None,
        "--precision",
        help="Least precise date accepted: year | month | day (date)",
    ),
    # geo
    geometry_types: Optional[str] = typer.Option(
        None,
        "--geometry-types",
        help="Comma-separated shapes allowed, e.g. Point,Polygon (geo)",
    ),
    bbox: Optional[str] = typer.Option(
        None,
        "--bbox",
        help="Allowed area as WEST,SOUTH,EAST,NORTH in degrees; west greater "
        "than east crosses the 180th meridian (geo)",
    ),
    clear_restrictions: bool = typer.Option(
        False, "--clear-restrictions", help="Remove all restrictions"
    ),
) -> None:
    """Update a field's name, label, required flag, or restrictions."""
    has_restriction_flags = any(
        v is not None
        for v in [
            min_val,
            max_val,
            choices,
            max_length,
            accept,
            max_size,
            unit,
            precision,
            geometry_types,
            bbox,
        ]
    )

    if (
        rename is None
        and label is None
        and required is None
        and not has_restriction_flags
        and not clear_restrictions
    ):
        console.print(
            "[error]Provide at least one of: --rename, --label, --required/--optional, restriction flags, --clear-restrictions.[/error]"
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
            all_datasets = ctx.dataset_svc.list_all(with_count=False)
            affected = []
            for d in all_datasets:
                # Counted in SQL: records of this schema without a value.
                missing = ctx.record_svc.count_records(
                    RecordQuery(
                        dataset=d.name,
                        schema=schema_name,
                        filter_tree={
                            "field": field_name,
                            "op": "is_null",
                            "value": True,
                        },
                    )
                )
                if missing:
                    affected.append((d.name, missing))
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
            if dtype == "longtext" and max_length is not None:
                new_restrictions["max_length"] = max_length
            if dtype in ("file", "file_list"):
                if accept:
                    new_restrictions["accept"] = accept
                if max_size is not None:
                    new_restrictions["max_size"] = max_size
            new_restrictions.update(
                _typed_restrictions(dtype, unit, precision, geometry_types, bbox)
            )
            old_unit = (field.restrictions or {}).get("unit")
            if unit is not None and old_unit and old_unit != unit:
                console.print(
                    f"[warning]This relabels '{field_name}' from {old_unit} to {unit}. "
                    "Stored values are NOT converted: use it only to correct a wrong "
                    "label. For a different unit going forward, add a new field.[/warning]"
                )
                typer.confirm("Relabel the unit anyway?", abort=True)

        updated = ctx.schema_svc.update_field(
            schema_name,
            field_name,
            new_name=rename,
            required=required,
            restrictions=new_restrictions,
            label=... if label is None else label,
        )
        ctx.commit()
        parts = [f"'{updated.name}'"]
        parts.append("required" if updated.required else "optional")
        if updated.restrictions:
            parts.append(str(updated.restrictions))
        console.print(f"[success]Updated field: {' · '.join(parts)}[/success]")
    except (NotFoundError, AlreadyExistsError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("remove-field")
def schema_remove_field(
    schema_name: str = typer.Argument(..., help="Schema containing the field"),
    field_name: str = typer.Argument(..., help="Field to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Remove a field from a schema.

    Reversible: the field goes to Recently Deleted and every record keeps the
    value it held for it. Bring it back with `civex schema restore-field`
    (find its ID with `civex trash list --kind field`).
    """
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


@app.command("restore-field")
def schema_restore_field(
    schema_name: str = typer.Argument(..., help="Schema the field was removed from"),
    field_id: str = typer.Argument(
        ..., help="ID of the removed field (see `civex trash list --kind field`)"
    ),
) -> None:
    """Restore a removed field, with the values records still hold for it."""
    import uuid

    try:
        parsed = uuid.UUID(field_id)
    except ValueError:
        console.print(
            "[error]That is not a field ID. Find it with "
            "`civex trash list --kind field` (give the full ID).[/error]"
        )
        raise typer.Exit(1)
    ctx = _ctx()
    try:
        field = ctx.schema_svc.restore_field(schema_name, parsed)
        ctx.commit()
        console.print(
            f"[success]Restored field '{field.name}' on '{schema_name}'.[/success]"
        )
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("delete")
def schema_delete(
    name: str = typer.Argument(..., help="Schema name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete a schema (and the records typed by it) to Recently Deleted.

    Reversible with `civex schema restore` within the retention window
    (see `civex trash list`); `civex schema purge` deletes permanently.
    """
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


@app.command("restore")
def schema_restore(name: str = typer.Argument(..., help="Schema name")) -> None:
    """Restore a soft-deleted schema (and the records cascade-deleted with it)."""
    ctx = _ctx()
    try:
        ctx.schema_svc.restore(name)
        ctx.commit()
        console.print(f"[success]Restored '{name}'.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("purge")
def schema_purge(
    name: str = typer.Argument(..., help="Schema name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Permanently delete a schema that's already in Recently Deleted. Irreversible."""
    if not yes:
        typer.confirm(
            f"Permanently delete '{name}'? This cannot be undone.", abort=True
        )
    ctx = _ctx()
    try:
        ctx.schema_svc.purge(name)
        ctx.commit()
        console.print(f"[success]Permanently deleted '{name}'.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("lint")
def schema_lint() -> None:
    """Report schema and field names that aren't valid slugs.

    Names are validated when they're created or renamed, so anything listed
    here predates that rule. Nothing is broken — these names still resolve —
    but they read badly in workflow YAML and CSV headers. Rename with
    `civex schema update --rename` / `civex schema update-field --rename`
    and move the human-readable text to `--label`.
    """
    ctx = _ctx()
    issues = ctx.schema_svc.lint_names()
    if not issues:
        console.print("[success]All schema and field names are valid slugs.[/success]")
        return

    table = Table("Kind", "Schema", "Name", "Suggested")
    for issue in issues:
        table.add_row(
            issue.kind,
            issue.schema_name,
            issue.name,
            issue.suggestion or "[dim]—[/dim]",
        )
    console.print(table)
    console.print(
        f"\n[warning]{len(issues)} name(s) are not valid slugs.[/warning] "
        "Renaming is safe for stored records (record data is keyed by field "
        "UUID), but update any workflow YAML that references the old name."
    )
