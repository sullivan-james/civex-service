from __future__ import annotations

import json
from typing import Any, Optional

import typer
from rich.markup import escape
from rich.table import Table

from civex.cli.utils import get_ctx
from civex.console import console
from civex.domain.dtos import ExportDefinitionDTO
from civex.domain.exceptions import CivexError
from civex.domain.file_access import LAYOUTS
from civex.domain.tables import FORMATS

app = typer.Typer(
    help="Exports saved with a schema: which files, how they are laid out",
    no_args_is_help=True,
)

_LAYOUT_HELP = (
    "tree: a folder per record above each file (default); grouped: the folders "
    "above, with the records that hold the files gathered into one folder named "
    "for their kind (Encounter/Recording/Selections); flat: every file in one "
    f"folder. One of: {', '.join(LAYOUTS)}."
)


_TABLE_HELP = (
    "Also make a table. On its own it is one table per kind of record the export "
    "holds, written at the top and named for the kind (Selections.csv); the "
    "--table-* options say which records are its rows and where it is written. "
    f"One of: {', '.join(FORMATS)}."
)
_OF_OPTION = typer.Option(
    None,
    "--table-of",
    help="The kind of record that is the table's rows: those the export takes, the "
    "ones above them, and (for a saved export) the ones beneath.",
)
_IN_OPTION = typer.Option(
    None,
    "--table-in",
    help="Write the table in the folder of each record of this kind, holding the "
    "--table-of records that are that record or beneath it (the same kind gives "
    "each record its own). Omit to write it once, at the top. Needs --layout tree.",
)
_SHAPE_OPTION = typer.Option(
    None,
    "--table-shape",
    help="rows (a row per record, the default) or fields (one record's fields as "
    "field/value pairs; needs --table-in the same kind as --table-of).",
)
_NAME_OPTION = typer.Option(
    None,
    "--table-name",
    help="The file's name without its extension, as a template over the folder's "
    "record ('{schema}', '{id}', its fields). Omit to name it for what it holds.",
)
_KEEP_EMPTY_OPTION = typer.Option(
    False,
    "--table-keep-empty",
    help="Also write a table (just its header) in a folder with no rows.",
)
_TABLES_JSON_OPTION = typer.Option(
    None,
    "--tables-json",
    help="Several tables at once, as a JSON list of objects with the keys format, "
    "columns, kind, where, shape, name and skip_empty (as in the HTTP API).",
)


def _tables(
    table: Optional[str],
    column: Optional[list[str]],
    of: Optional[str],
    in_: Optional[str],
    shape: Optional[str],
    name: Optional[str],
    keep_empty: bool,
    tables_json: Optional[str],
) -> list[dict[str, Any]] | None:
    """The tables the options describe, or None when none were asked for. One
    table is described by the --table options; several by --tables-json."""
    singles = [column, of, in_, shape, name]
    if tables_json:
        if table or any(singles) or keep_empty:
            console.print(
                "[error]--tables-json replaces --table and the --table-* options: "
                "give one or the other.[/error]"
            )
            raise typer.Exit(1)
        try:
            value = json.loads(tables_json)
        except ValueError as e:
            console.print(
                f"[error]--tables-json is not valid JSON: {escape(str(e))}[/error]"
            )
            raise typer.Exit(1)
        if not isinstance(value, list) or not all(isinstance(t, dict) for t in value):
            console.print(
                "[error]--tables-json must be a JSON list of objects.[/error]"
            )
            raise typer.Exit(1)
        return value
    if not table:
        if any(singles) or keep_empty:
            console.print(
                "[error]The --table-* options and --column need --table FORMAT.[/error]"
            )
            raise typer.Exit(1)
        return None
    return [
        {
            "format": table,
            "columns": list(column) if column else None,
            "kind": of,
            "where": in_,
            "shape": shape or "rows",
            "name": name,
            "skip_empty": not keep_empty,
        }
    ]


def _table_line(t: dict[str, Any]) -> str:
    """One table, as a person says it: 'csv table' for the simple form, 'csv of
    selection in each recording' once it says what its rows are and where it goes."""
    columns = t.get("columns")
    extra = f" ({len(columns)} columns)" if columns else ""
    if not t.get("kind"):
        return f"{t['format']} table{extra}"
    place = f"in each {t['where']}" if t.get("where") else "at the top"
    shape = " (field/value)" if t.get("shape") == "fields" else ""
    return f"{t['format']} of {t['kind']} {place}{shape}{extra}"


_COLUMN_HELP = (
    "A column of the table (repeat for several, in order): a field, a "
    "ref_field.target_field join, or id/schema/created_at/updated_at. Omit for "
    "the id and every field."
)


def _filter(text: Optional[str]) -> dict[str, Any] | None:
    if text is None:
        return None
    try:
        value = json.loads(text)
    except ValueError as e:
        console.print(f"[error]--filter is not valid JSON: {escape(str(e))}[/error]")
        raise typer.Exit(1)
    if not isinstance(value, dict):
        console.print("[error]--filter must be a JSON filter tree (an object).[/error]")
        raise typer.Exit(1)
    return value


def _describe(d: ExportDefinitionDTO) -> str:
    kind = d.holder or "any kind beneath"
    files = ", ".join(d.fields) if d.fields else "every file field"
    parts = (
        [f"{files} of {kind}", d.files_layout]
        if d.include_files
        else [f"table of {kind}"]
    )
    parts.extend(_table_line(t) for t in d.tables)
    if d.filter_tree:
        parts.append("filtered")
    return " · ".join(parts)


def _fail(e: CivexError) -> None:
    console.print(f"[error]{escape(str(e))}[/error]")
    raise typer.Exit(1)


@app.command("list")
def exports_list(
    schema: str = typer.Argument(..., help="Schema whose exports to list"),
    available_on: bool = typer.Option(
        False,
        "--available",
        help="Instead, every export that can run within a record of this schema: "
        "those saved with it and with the schemas above it",
    ),
) -> None:
    """List the exports saved with a schema.

    An export is part of a schema's setup, like its fields. It is run from a
    collection or a record: `civex files export --export <schema>/<name>`.
    """
    ctx = get_ctx()
    try:
        svc = ctx.export_def_svc
        found = svc.available_on(schema) if available_on else svc.list_for(schema)
    except CivexError as e:
        _fail(e)
        return
    finally:
        ctx.close()
    if not found:
        console.print("[dim]No exports.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    for column in ("Schema", "Name", "What it exports"):
        table.add_column(column)
    for d in found:
        table.add_row(escape(d.schema_name), escape(d.name), escape(_describe(d)))
    console.print(table)


@app.command("show")
def exports_show(
    schema: str = typer.Argument(..., help="Schema the export is saved with"),
    name: str = typer.Argument(..., help="Export name"),
) -> None:
    """Show one export in full."""
    ctx = get_ctx()
    try:
        d = ctx.export_def_svc.get(schema, name)
    except CivexError as e:
        _fail(e)
        return
    finally:
        ctx.close()
    console.print(f"[bold]{escape(d.schema_name)}/{escape(d.name)}[/bold]")
    console.print(f"  kind of record: {escape(d.holder or 'any kind beneath')}")
    console.print(
        f"  file fields:    {escape(', '.join(d.fields) if d.fields else 'every one')}"
    )
    console.print(
        f"  files:          {'yes' if d.include_files else 'no (table alone)'}"
    )
    console.print(f"  layout:         {d.files_layout}")
    for t in d.tables:
        columns = t.get("columns")
        console.print(f"  table:          {escape(_table_line(t))}")
        if t.get("name"):
            console.print(f"    named:        {escape(t['name'])}")
        console.print(
            f"    columns:      {escape(', '.join(columns) if columns else 'id and every field')}"
        )
    if d.filter_tree:
        console.print(f"  filter:         {escape(json.dumps(d.filter_tree))}")


@app.command("add")
def exports_add(
    schema: str = typer.Argument(..., help="Schema to save the export with"),
    name: str = typer.Argument(..., help="What to call it, in your own words"),
    kind: Optional[str] = typer.Option(
        None,
        "--kind",
        "-k",
        help="The kind of record that holds the files: the schema itself or a "
        "kind beneath it. Omit for any kind beneath.",
    ),
    field: Optional[list[str]] = typer.Option(
        None,
        "--field",
        "-f",
        help="A file field to export (repeat for several). Omit for every one.",
    ),
    filter_: Optional[str] = typer.Option(
        None,
        "--filter",
        help="A filter on the records that hold the files, as a JSON filter tree "
        '(e.g. \'{"field": "quality", "op": "eq", "value": "good"}\'). Needs --kind.',
    ),
    layout: str = typer.Option("tree", "--layout", help=_LAYOUT_HELP),
    table: Optional[str] = typer.Option(None, "--table", "-t", help=_TABLE_HELP),
    column: Optional[list[str]] = typer.Option(
        None, "--column", "-C", help=_COLUMN_HELP
    ),
    table_of: Optional[str] = _OF_OPTION,
    table_in: Optional[str] = _IN_OPTION,
    table_shape: Optional[str] = _SHAPE_OPTION,
    table_name: Optional[str] = _NAME_OPTION,
    table_keep_empty: bool = _KEEP_EMPTY_OPTION,
    tables_json: Optional[str] = _TABLES_JSON_OPTION,
    no_files: bool = typer.Option(
        False, "--no-files", help="Make the tables alone, without the files."
    ),
) -> None:
    """Save an export with a schema.

    For example, adding an export called contours to the encounter schema with
    --kind selection, --field contour and --layout flat takes the contour files
    of every selection beneath an encounter and puts them in one folder. It is
    then offered on collections that use the schema and on records of it (and of
    the schemas beneath it, down to the kind that holds the files).
    """
    tables = _tables(
        table,
        column,
        table_of,
        table_in,
        table_shape,
        table_name,
        table_keep_empty,
        tables_json,
    )
    ctx = get_ctx()
    try:
        d = ctx.export_def_svc.create(
            schema,
            name,
            holder=kind,
            fields=list(field or []),
            filter_tree=_filter(filter_),
            files_layout=layout,
            include_files=not no_files,
            tables=tables,
        )
        ctx.commit()
    except CivexError as e:
        _fail(e)
        return
    finally:
        ctx.close()
    console.print(
        f"[success]Saved {escape(d.schema_name)}/{escape(d.name)}[/success]: "
        f"{escape(_describe(d))}"
    )


@app.command("set")
def exports_set(
    schema: str = typer.Argument(..., help="Schema the export is saved with"),
    name: str = typer.Argument(..., help="Export name"),
    rename: Optional[str] = typer.Option(None, "--rename", help="A new name"),
    kind: Optional[str] = typer.Option(
        None, "--kind", "-k", help="Change the kind of record that holds the files"
    ),
    any_kind: bool = typer.Option(
        False, "--any-kind", help="Take files from any kind beneath the schema"
    ),
    field: Optional[list[str]] = typer.Option(
        None, "--field", "-f", help="Replace the file fields (repeat for several)"
    ),
    all_fields: bool = typer.Option(
        False, "--all-fields", help="Export every file field"
    ),
    filter_: Optional[str] = typer.Option(
        None, "--filter", help="Replace the filter (a JSON filter tree)"
    ),
    no_filter: bool = typer.Option(False, "--no-filter", help="Remove the filter"),
    layout: Optional[str] = typer.Option(None, "--layout", help=_LAYOUT_HELP),
    table: Optional[str] = typer.Option(None, "--table", "-t", help=_TABLE_HELP),
    column: Optional[list[str]] = typer.Option(
        None, "--column", "-C", help=_COLUMN_HELP
    ),
    table_of: Optional[str] = _OF_OPTION,
    table_in: Optional[str] = _IN_OPTION,
    table_shape: Optional[str] = _SHAPE_OPTION,
    table_name: Optional[str] = _NAME_OPTION,
    table_keep_empty: bool = _KEEP_EMPTY_OPTION,
    tables_json: Optional[str] = _TABLES_JSON_OPTION,
    no_table: bool = typer.Option(False, "--no-table", help="Remove every table"),
    files: Optional[bool] = typer.Option(
        None, "--files/--no-files", help="Take the files, or make the table alone"
    ),
) -> None:
    """Change an export.

    Only what you name changes. The result is checked as a whole, so a kind that
    doesn't have the chosen fields is refused.
    """
    if kind and any_kind:
        console.print("[error]Give --kind or --any-kind, not both.[/error]")
        raise typer.Exit(1)
    if field and all_fields:
        console.print("[error]Give --field or --all-fields, not both.[/error]")
        raise typer.Exit(1)
    if filter_ and no_filter:
        console.print("[error]Give --filter or --no-filter, not both.[/error]")
        raise typer.Exit(1)
    changes: dict[str, Any] = {}
    if kind:
        changes["holder"] = kind
    if any_kind:
        changes["holder"] = None
    if field:
        changes["fields"] = list(field)
    if all_fields:
        changes["fields"] = []
    if filter_:
        changes["filter_tree"] = _filter(filter_)
    if no_filter:
        changes["filter_tree"] = None
    if layout:
        changes["files_layout"] = layout
    if table and no_table:
        console.print("[error]Give --table or --no-table, not both.[/error]")
        raise typer.Exit(1)
    tables = _tables(
        table,
        column,
        table_of,
        table_in,
        table_shape,
        table_name,
        table_keep_empty,
        tables_json,
    )
    if tables is not None:
        changes["tables"] = tables
    if no_table:
        changes["tables"] = []
    if files is not None:
        changes["include_files"] = files
    if not changes and not rename:
        console.print("[error]Nothing to change.[/error]")
        raise typer.Exit(1)
    ctx = get_ctx()
    try:
        d = ctx.export_def_svc.update(schema, name, new_name=rename, **changes)
        ctx.commit()
    except CivexError as e:
        _fail(e)
        return
    finally:
        ctx.close()
    console.print(
        f"[success]Updated {escape(d.schema_name)}/{escape(d.name)}[/success]: "
        f"{escape(_describe(d))}"
    )


@app.command("remove")
def exports_remove(
    schema: str = typer.Argument(..., help="Schema the export is saved with"),
    name: str = typer.Argument(..., help="Export name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
) -> None:
    """Delete a saved export.

    Folders it already made are left; see `civex files exports`.
    """
    if not yes and not typer.confirm(f"Delete the export {schema}/{name}?"):
        raise typer.Exit(1)
    ctx = get_ctx()
    try:
        ctx.export_def_svc.delete(schema, name)
        ctx.commit()
    except CivexError as e:
        _fail(e)
        return
    finally:
        ctx.close()
    console.print(f"[success]Deleted {escape(schema)}/{escape(name)}.[/success]")
