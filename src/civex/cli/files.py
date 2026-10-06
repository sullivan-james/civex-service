from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.markup import escape
from rich.table import Table

from civex.cli.utils import format_bytes, get_ctx
from civex.console import console
from civex.domain.exceptions import CivexError
from civex.domain.file_access import (
    EXPORT_MODES,
    FilePlan,
    FileSelection,
    FilesScatteredError,
    FilesUnavailableError,
    LAYOUT_TREE,
    LAYOUTS,
    LinksNotPossibleError,
)
from civex.domain.query import RecordQuery
from civex.domain.tables import FORMATS, TableSpec

app = typer.Typer(
    help="Reach stored files by name and folder, the way the records are arranged",
    no_args_is_help=True,
)


def _selection(
    collection: Optional[str],
    schema: Optional[str],
    under: Optional[str],
    fields: Optional[list[str]],
    where: Optional[list[str]],
    search: Optional[str],
    view: Optional[str] = None,
    layout: Optional[str] = None,
    export: Optional[str] = None,
    table: Optional[str] = None,
    columns: Optional[list[str]] = None,
    no_files: bool = False,
) -> FileSelection:
    selection = _files_selection(
        collection, schema, under, fields, where, search, view, layout, export
    )
    if table:
        if table not in FORMATS:
            console.print(
                f"[error]--table must be one of: {', '.join(FORMATS)}[/error]"
            )
            raise typer.Exit(1)
        selection.tables = [TableSpec(table, columns or None)]
    elif columns:
        console.print("[error]--column needs --table FORMAT.[/error]")
        raise typer.Exit(1)
    if no_files:
        if not selection.tables:
            console.print("[error]--no-files needs --table FORMAT.[/error]")
            raise typer.Exit(1)
        selection.files = False
    return selection


def _files_selection(
    collection: Optional[str],
    schema: Optional[str],
    under: Optional[str],
    fields: Optional[list[str]],
    where: Optional[list[str]],
    search: Optional[str],
    view: Optional[str] = None,
    layout: Optional[str] = None,
    export: Optional[str] = None,
) -> FileSelection:
    if export:
        # An export saved with a schema: its kind, fields, filter and layout. The
        # collection (--in) and/or record (--under) it is run on are given here.
        if "/" not in export:
            console.print(
                "[error]--export is `schema/name`, e.g. encounter/contours.[/error]"
            )
            raise typer.Exit(1)
        schema_name, _, export_name = export.partition("/")
        ctx = get_ctx()
        try:
            definition = ctx.export_def_svc.get(schema_name, export_name)
            run = ctx.export_def_svc.selection(
                definition, collection=collection, within=under
            )
        except CivexError as e:
            console.print(f"[error]{escape(str(e))}[/error]")
            raise typer.Exit(1)
        finally:
            ctx.close()
        if layout:
            run.layout = layout
        return run
    if view:
        # A saved view is a preset: its filter, its file columns and its layout.
        if "/" not in view:
            console.print(
                "[error]--view is `schema/view`, e.g. recording/tables.[/error]"
            )
            raise typer.Exit(1)
        schema_name, _, view_name = view.partition("/")
        ctx = get_ctx()
        try:
            selection = ctx.view_svc.file_selection(schema_name, view_name)
        except CivexError as e:
            console.print(f"[error]{escape(str(e))}[/error]")
            raise typer.Exit(1)
        finally:
            ctx.close()
        if selection is None:
            console.print(
                f"[error]The view '{escape(view)}' has no file columns.[/error]"
            )
            raise typer.Exit(1)
        selection.query.dataset = collection
        selection.query.within = under
        if layout:
            selection.layout = layout
        return selection
    if not (collection or schema or under):
        console.print(
            "[error]Say which files: give --in, --schema, --under, --view or "
            "--export.[/error]"
        )
        raise typer.Exit(1)
    return FileSelection(
        query=RecordQuery(
            dataset=collection,
            schema=schema,
            within=under,
            where=where or [],
            search=search,
        ),
        fields=fields or None,
        layout=layout or LAYOUT_TREE,
    )


_IN = typer.Option(None, "--in", "-c", help="Only this collection")
_SCHEMA = typer.Option(None, "--schema", "-s", help="Only records of this schema")
_UNDER = typer.Option(
    None,
    "--under",
    "-u",
    help="A record (id or prefix): its files and those of everything beneath it. "
    "Paths start below it. With --schema, only that schema's records.",
)
_FIELD = typer.Option(
    None, "--field", "-f", help="Only this file field (repeat for several)"
)
_WHERE = typer.Option(None, "--where", "-w", help="Filter: field=value (repeatable)")
_SEARCH = typer.Option(None, "--search", help="Text to find in the records' values")
_VIEW = typer.Option(
    None,
    "--view",
    help="A saved view, as schema/view: its filter, its file columns and its "
    "layout (--in/--under still narrow it).",
)
_EXPORT = typer.Option(
    None,
    "--export",
    "-e",
    help="An export saved with a schema, as schema/name (see `civex schema "
    "exports`): its kind, file fields, filter and layout. Run it in a collection "
    "(--in) and/or within a record (--under).",
)
_TABLE = typer.Option(
    None,
    "--table",
    "-t",
    help=f"Also make a table of the records, one per kind of record, named for the "
    f"kind (Selections.csv). One of: {', '.join(FORMATS)}.",
)
_COLUMN = typer.Option(
    None,
    "--column",
    "-C",
    help="A column of the table (repeat for several, in order): a field, a "
    "ref_field.target_field join, or id/schema/created_at/updated_at. Default: "
    "the id and every field.",
)
_NO_FILES = typer.Option(
    False, "--no-files", help="Make the table alone, without the files."
)
_LAYOUT = typer.Option(
    None,
    "--layout",
    help="tree: a folder per record above each file (default); grouped: the "
    "folders above, but the records holding the files gathered into one folder "
    "named for their kind (Encounter/Recording/Selections); flat: every file in "
    f"one folder. One of: {', '.join(LAYOUTS)}.",
)


def _print_unreachable(plan: FilePlan) -> None:
    console.print(f"[warning]{escape(plan.summary())}[/warning]")
    for g in plan.unavailable:
        where = f"'{g.volume}'" if g.volume else "no known drive"
        console.print(
            f"  • {g.files} file(s) on {where}: {escape(g.reason or g.state)}"
        )
        if g.fix:
            console.print(f"    {escape(g.fix)}")
        if g.records:
            console.print(f"    records: {escape(', '.join(g.records))}")


@app.command("list")
def files_list(
    collection: Optional[str] = _IN,
    schema: Optional[str] = _SCHEMA,
    under: Optional[str] = _UNDER,
    field: Optional[list[str]] = _FIELD,
    where: Optional[list[str]] = _WHERE,
    search: Optional[str] = _SEARCH,
    view: Optional[str] = _VIEW,
    export: Optional[str] = _EXPORT,
    layout: Optional[str] = _LAYOUT,
    paths: bool = typer.Option(
        False,
        "--paths",
        help="Print where each reachable file is on disk, one per line, for scripts",
    ),
) -> None:
    """List the files of some records by the path they would have as folders.

    Shows what can be reached now. A file on a drive that isn't connected is
    listed with the drive's name instead of a path.
    """
    selection = _selection(
        collection, schema, under, field, where, search, view, layout, export
    )
    ctx = get_ctx()
    try:
        plan = ctx.file_access_svc.plan(selection, with_sources=paths)
    except CivexError as e:
        console.print(f"[error]{escape(str(e))}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()

    if paths:
        for item in plan.items:
            if item.source:
                typer.echo(item.source)
        if not plan.complete:
            _print_unreachable(plan)
        return
    if not plan.items:
        console.print("[dim]No files.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Path")
    table.add_column("Size", justify="right")
    table.add_column("Where")
    for item in plan.items:
        where_text = (
            item.volume or ""
            if item.available
            else f"[warning]{escape(item.volume or 'not stored')} (unavailable)[/warning]"
        )
        table.add_row(escape(item.path), format_bytes(item.size), where_text)
    console.print(table)
    console.print(f"[dim]{plan.total} file(s), {format_bytes(plan.bytes)}[/dim]")
    if not plan.complete:
        _print_unreachable(plan)


@app.command("export")
def files_export(
    dest: Optional[Path] = typer.Argument(
        None,
        help="Advanced: a folder to build in (empty, or an earlier export). "
        "Leave out to use civex's own exports folder, which `civex files "
        "exports` can list and clean up.",
    ),
    collection: Optional[str] = _IN,
    schema: Optional[str] = _SCHEMA,
    under: Optional[str] = _UNDER,
    field: Optional[list[str]] = _FIELD,
    where: Optional[list[str]] = _WHERE,
    search: Optional[str] = _SEARCH,
    view: Optional[str] = _VIEW,
    export: Optional[str] = _EXPORT,
    layout: Optional[str] = _LAYOUT,
    table: Optional[str] = _TABLE,
    column: Optional[list[str]] = _COLUMN,
    no_files: bool = _NO_FILES,
    mode: str = typer.Option(
        "link",
        "--mode",
        help="link: hard links in a folder on the drive that holds the files, so "
        "nothing is copied (refused if the files are on several drives); copy: "
        "real copies on one drive (--to). A link is the stored file itself, so "
        "don't edit it in place.",
    ),
    to: Optional[str] = typer.Option(
        None,
        "--to",
        help="With --mode copy: the drive (volume name) to copy onto. Default: "
        "the project folder.",
    ),
    name: Optional[str] = typer.Option(
        None, "--name", help="Name of the export folder (default: from the selection)"
    ),
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help="Go ahead without the files that can't be reached (they are listed "
        "in MISSING.txt)",
    ),
) -> None:
    """Build a folder of the files, named and arranged by their records.

    With --table FORMAT the folder also holds a table of those records (one per
    kind, named for it: Selections.csv, or .tsv .xlsx .json .jsonl), whose file
    columns say where each file is in the folder; --column picks its columns and
    --no-files makes the table alone.

    Prints what can't be reached first. If anything can't (a drive that isn't
    connected) nothing is made unless you agree, or pass --allow-partial.
    With --mode link, files spread over more than one drive can't be gathered
    into one linked folder; use --mode copy --to <drive> for those. Running it
    again on the same folder updates it: new files are added and ones no
    longer selected are removed. A folder holding other files is refused, so
    nothing of yours is touched. Remove exports with `civex files exports
    remove`.
    """
    if mode not in EXPORT_MODES:
        console.print(
            f"[error]--mode must be one of: {', '.join(EXPORT_MODES)}[/error]"
        )
        raise typer.Exit(1)
    selection = _selection(
        collection,
        schema,
        under,
        field,
        where,
        search,
        view,
        layout,
        export,
        table,
        column,
        no_files,
    )
    folder_name = name or (
        "-".join(p for p in (collection, schema, under and under[:8]) if p) or "files"
    )
    ctx = get_ctx()
    try:
        svc = ctx.file_access_svc
        plan = svc.plan(selection, fetch=True)
        if not plan.items and not plan.tables:
            console.print("[dim]Nothing to export.[/dim]")
            return
        if not plan.complete:
            _print_unreachable(plan)
            go = allow_partial or (
                sys.stdin.isatty()
                and typer.confirm(f"Export the {plan.available} available file(s)?")
            )
            if not go:
                console.print("[error]Nothing was exported.[/error]")
                raise typer.Exit(1)
        if dest is not None:
            result = svc.export(selection, dest, mode, allow_partial=True, plan=plan)
        else:
            result = svc.export_managed(
                selection, folder_name, mode, to, allow_partial=True, plan=plan
            )
    except FilesScatteredError as e:
        console.print(f"[error]{escape(str(e))}[/error]")
        console.print(
            "Try: civex files export ... --mode copy --to <drive>  "
            "(civex store list shows the drives)"
        )
        raise typer.Exit(1)
    except (LinksNotPossibleError, FilesUnavailableError, CivexError) as e:
        console.print(f"[error]{escape(str(e))}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()

    where_text = f" on {result.location}" if result.location else ""
    console.print(
        f"[success]{result.dest}[/success]{where_text}: {result.copied} copied, "
        f"{result.linked} linked, {result.unchanged} already there, "
        f"{result.removed} removed"
        + (f", {result.tables} table(s) written." if result.tables else ".")
    )
    if result.linked:
        console.print(
            "[dim]A linked file is the stored file itself: don't edit it in place "
            "(use --mode copy for files you will change).[/dim]"
        )
    if result.missing:
        console.print(
            f"[warning]{len(result.missing)} file(s) left out; see MISSING.txt.[/warning]"
        )
        raise typer.Exit(2)


@app.command("download")
def files_download(
    output: Path = typer.Argument(
        ..., help="Where to write it: a .zip, or the table's own file"
    ),
    collection: Optional[str] = _IN,
    schema: Optional[str] = _SCHEMA,
    under: Optional[str] = _UNDER,
    field: Optional[list[str]] = _FIELD,
    where: Optional[list[str]] = _WHERE,
    search: Optional[str] = _SEARCH,
    view: Optional[str] = _VIEW,
    export: Optional[str] = _EXPORT,
    layout: Optional[str] = _LAYOUT,
    table: Optional[str] = _TABLE,
    column: Optional[list[str]] = _COLUMN,
    no_files: bool = _NO_FILES,
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help="Go ahead without the files that can't be reached (MISSING.txt lists them)",
    ),
) -> None:
    """Write the selection as one file: a zip of the files and their tables, or,
    when it is a single table and nothing else, that table.

    The same paths and tables as `civex files export`, for taking elsewhere.
    """
    import shutil
    import tempfile

    from civex.services.archive import build_download

    selection = _selection(
        collection,
        schema,
        under,
        field,
        where,
        search,
        view,
        layout,
        export,
        table,
        column,
        no_files,
    )
    ctx = get_ctx()
    scratch = Path(tempfile.mkdtemp(prefix="civex-download-"))
    try:
        plan = ctx.file_access_svc.plan(selection, fetch=True)
        if not plan.complete:
            _print_unreachable(plan)
            if not allow_partial:
                console.print("[error]Nothing was written.[/error]")
                raise typer.Exit(1)
        download = build_download(
            ctx.file_access_svc, ctx.file_svc, selection, plan, scratch, output.stem
        )
        shutil.move(str(download.path), output)
    except FileNotFoundError as e:
        console.print(f"[error]A file is no longer stored: {escape(str(e))}[/error]")
        raise typer.Exit(1)
    except CivexError as e:
        console.print(f"[error]{escape(str(e))}[/error]")
        raise typer.Exit(1)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        ctx.close()
    console.print(f"[success]Wrote {output}[/success]")


@app.command("gather")
def files_gather(
    to: str = typer.Option(
        ..., "--to", help="The drive (volume name) to gather the files onto"
    ),
    collection: Optional[str] = _IN,
    schema: Optional[str] = _SCHEMA,
    under: Optional[str] = _UNDER,
    field: Optional[list[str]] = _FIELD,
    where: Optional[list[str]] = _WHERE,
    search: Optional[str] = _SEARCH,
    view: Optional[str] = _VIEW,
    export: Optional[str] = _EXPORT,
    layout: Optional[str] = _LAYOUT,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would move and stop."
    ),
) -> None:
    """Move just these files onto one drive, so they can be linked as a folder.

    Only the files you select move, not the rest of their collections. It is
    an ordinary move (checked before the original is removed, safe to stop at
    any moment, queued behind any other); once it has finished,
    `civex files export` can make a linked folder of them all. Use
    `civex files list` first to see what you are selecting.
    """
    from civex.cli.transfers import _start
    from civex.domain.transfers import KIND_FILES, TransferSpec

    selection = _selection(
        collection, schema, under, field, where, search, view, layout, export
    )
    ctx = get_ctx()
    try:
        svc = ctx.file_access_svc
        plan = svc.plan(selection, fetch=True)
        shas = svc.files_to_gather(plan, to)
    except CivexError as e:
        console.print(f"[error]{escape(str(e))}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    if not shas:
        console.print(f"[dim]Every reachable file is already on '{escape(to)}'.[/dim]")
        return
    if not plan.complete:
        _print_unreachable(plan)
        console.print("[dim]Those can't be moved until they can be reached.[/dim]")
    _start(
        TransferSpec(kind=KIND_FILES, targets=[to], shas=shas, freeze_sources=False),
        dry_run,
    )


exports_app = typer.Typer(
    help="See and clean up the folders `civex files export` made",
    no_args_is_help=True,
)
app.add_typer(exports_app, name="exports")


@exports_app.command("list")
def exports_list() -> None:
    """List export folders in the project and on each connected drive.

    Links take no space; copies do. Exports on a drive that isn't connected
    can't be listed until it is plugged in.
    """
    ctx = get_ctx()
    try:
        exports = ctx.file_access_svc.list_exports()
    finally:
        ctx.close()
    if not exports:
        console.print("[dim]No exports.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    for column in ("Name", "Where", "Files", "Links", "Copies", "Space", "Updated"):
        table.add_column(column)
    for e in exports:
        table.add_row(
            escape(e.name),
            escape(e.location),
            str(e.files),
            "?" if e.linked is None else str(e.linked),
            "?" if e.copied is None else str(e.copied),
            "?" if e.bytes_on_disk is None else format_bytes(e.bytes_on_disk),
            (e.updated or "")[:16].replace("T", " "),
        )
    console.print(table)


@exports_app.command("remove")
def exports_remove(
    names: Optional[list[str]] = typer.Argument(
        None,
        help="Exports to remove: `where/name` as listed (e.g. archive/hb-tables), "
        "or a folder path",
    ),
    all_: bool = typer.Option(False, "--all", help="Remove every export"),
    older_than: Optional[int] = typer.Option(
        None, "--older-than", min=0, help="Remove exports last updated over N days ago"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
) -> None:
    """Delete export folders: the links or copies they hold, then the folder.

    A link is removed without touching the stored file it points at, so
    nothing in civex is lost. Files in an export folder that civex didn't make
    are left (and so is the folder).
    """
    if not (names or all_ or older_than is not None):
        console.print("[error]Say which: names, --all or --older-than.[/error]")
        raise typer.Exit(1)
    ctx = get_ctx()
    try:
        svc = ctx.file_access_svc
        listed = svc.list_exports()
        chosen: list[str] = []
        cutoff = (
            (datetime.now(timezone.utc) - timedelta(days=older_than)).isoformat()
            if older_than is not None
            else None
        )
        for e in listed:
            if (
                all_
                or f"{e.location}/{e.name}" in (names or [])
                or e.path in (names or [])
                or (cutoff and e.updated and e.updated < cutoff)
            ):
                chosen.append(e.path)
        # A path that isn't in the listing (an export made with an explicit
        # folder) is still removable if it carries civex's marker.
        listed_paths = {e.path for e in listed}
        chosen += [
            n
            for n in (names or [])
            if "/" in n and n not in listed_paths and Path(n).is_absolute()
        ]
        if not chosen:
            console.print("[dim]Nothing matches.[/dim]")
            return
        if not yes:
            console.print(f"Remove {len(chosen)} export folder(s)?")
            for path in chosen:
                console.print(f"  {escape(path)}")
            if not typer.confirm("Remove them?"):
                raise typer.Exit(1)
        failed = 0
        for path in chosen:
            try:
                r = svc.remove_export(path)
            except CivexError as e:
                console.print(f"[error]{escape(path)}: {escape(str(e))}[/error]")
                failed += 1
                continue
            note = f", freed {format_bytes(r.freed_bytes)}" if r.freed_bytes else ""
            kept = (
                f"; kept {r.kept_files} file(s) that aren't the export's"
                if r.kept_files
                else ""
            )
            console.print(
                f"[success]{escape(path)}[/success]: removed {r.removed_files} "
                f"file(s){note}{kept}."
            )
        if failed:
            raise typer.Exit(1)
    finally:
        ctx.close()
