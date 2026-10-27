"""`civex bundle`: a project's data as one file another civex can read."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from civex.cli.utils import get_ctx
from civex.console import console
from civex.domain.bundle import EXTENSION, BundleError, ExportOptions, Manifest
from civex.domain.exceptions import NotFoundError
from civex.services.bundle_service import BundlePlan, ImportResult

app = typer.Typer(
    help=(
        "Move a project's data to another project as one file: schemas, "
        "collections, records (their ids kept), the files they cite, and the "
        "project's workflows and plugins."
    ),
    no_args_is_help=True,
)


def _size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _print_plan(plan: BundlePlan, title: str) -> None:
    table = Table(title=title, show_header=False, box=None)
    table.add_row("Schemas", str(plan.schemas))
    table.add_row(
        "Collections",
        f"{len(plan.collections)}"
        + (f" ({', '.join(plan.collections)})" if plan.collections else ""),
    )
    table.add_row("Records", str(plan.records))
    files = f"{plan.files} ({_size(plan.file_bytes)})"
    if not plan.include_files:
        files += " — not included"
    table.add_row("Files", files)
    table.add_row("Workflows", str(plan.workflows))
    table.add_row("Plugins", str(plan.plugins))
    console.print(table)
    if plan.include_files and plan.files_unreachable:
        console.print(
            f"  [warning]{plan.files_unreachable} file(s) are on no drive that can "
            "be reached now and were left out; the records still cite them.[/warning]"
        )


@app.command("export")
def export(
    output: Path = typer.Option(
        Path("civex-bundle" + EXTENSION), "--output", "-o", help="Where to write it"
    ),
    collection: Optional[list[str]] = typer.Option(
        None,
        "--collection",
        "-c",
        help="Only these collections' records and files (repeatable); default all",
    ),
    no_files: bool = typer.Option(
        False, "--no-files", help="Leave the stored files out (records still cite them)"
    ),
    no_data: bool = typer.Option(
        False, "--no-data", help="Structure only: no records and no files"
    ),
    no_workflows: bool = typer.Option(
        False, "--no-workflows", help="Leave workflows and plugins out"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Say what would go in without writing anything"
    ),
) -> None:
    """Write the project's data to one bundle file.

    A bundle is a zip holding the schemas, the collections and their records
    with their ids, the stored files those records cite (unless --no-files),
    and the project's workflows and plugins. Read it into another project with
    `civex bundle import`.
    """
    options = ExportOptions(
        include_records=not no_data,
        include_files=not no_data and not no_files,
        include_workflows=not no_workflows,
        collections=collection or None,
    )
    ctx = get_ctx()
    try:
        if dry_run:
            _print_plan(ctx.bundle_svc.plan_export(options), "Would export")
            return
        plan = ctx.bundle_svc.export(output, options)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    _print_plan(plan, f"Exported to {output}")
    console.print(f"[success]Wrote {output} ({_size(output.stat().st_size)})[/success]")


def _print_manifest(manifest: Manifest, path: Path) -> None:
    table = Table(title=str(path), show_header=False, box=None)
    table.add_row("Exported", manifest.exported_at or "unknown")
    table.add_row("By civex", manifest.civex_version or "unknown")
    table.add_row("Schemas", ", ".join(s["name"] for s in manifest.schemas) or "none")
    table.add_row(
        "Collections", ", ".join(c["name"] for c in manifest.collections) or "none"
    )
    table.add_row("Records", str(manifest.records))
    files = (
        f"{manifest.files.count} ({_size(manifest.files.bytes)})"
        if manifest.files.included
        else "not included"
    )
    if manifest.files.missing:
        files += f", {len(manifest.files.missing)} were unreachable when exported"
    table.add_row("Files", files)
    table.add_row("Workflows", str(manifest.workflows))
    table.add_row("Plugins", str(manifest.plugins))
    console.print(table)


@app.command("show")
def show(
    bundle_file: Path = typer.Argument(
        ..., help="A bundle written by `civex bundle export`"
    ),
) -> None:
    """Say what a bundle holds, without importing anything."""
    ctx = get_ctx()
    try:
        manifest = ctx.bundle_svc.inspect(bundle_file)
    except (NotFoundError, BundleError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    _print_manifest(manifest, bundle_file)


def _print_result(result: ImportResult) -> None:
    table = Table(title="Imported", show_header=False, box=None)
    schemas = f"{result.schemas_new} new"
    if result.schemas_existing:
        schemas += f", {len(result.schemas_existing)} already here"
    table.add_row("Schemas", schemas)
    collections = f"{result.collections_new} new"
    if result.collections_existing:
        collections += f", {len(result.collections_existing)} already here"
    table.add_row("Collections", collections)
    records = f"{result.records_added} added"
    if result.records_existing:
        records += f", {result.records_existing} already here"
    if result.records_skipped:
        records += f", {result.records_skipped} skipped"
    table.add_row("Records", records)
    files = f"{result.files_added} added"
    if result.files_missing:
        files += f", {result.files_missing} not in the bundle or here"
    if result.files_refused:
        files += f", {result.files_refused} refused (bytes did not match)"
    table.add_row("Files", files)
    table.add_row("Workflows", str(result.workflows))
    table.add_row("Plugins", str(result.plugins))
    console.print(table)
    for s in result.skipped:
        console.print(f"  [warning]Record {s.id[:8]} skipped: {s.reason}[/warning]")
    if result.records_skipped > len(result.skipped):
        console.print(
            f"  [warning]…and {result.records_skipped - len(result.skipped)} more.[/warning]"
        )
    for s in result.members_skipped:
        console.print(f"  [warning]{s.id} skipped: {s.reason}[/warning]")
    if result.plugins:
        console.print(
            "  [warning]Plugins are code. Read what was written to _civex/plugins/ "
            "before running workflows.[/warning]"
        )


@app.command("import")
def import_(
    bundle_file: Path = typer.Argument(
        ..., help="A bundle written by `civex bundle export`"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
) -> None:
    """Read a bundle into this project.

    Schemas are matched by name (one already here only gains the fields it
    lacks), collections by name (one already here is reused), and records by
    id (one already here, live or deleted, is left as it is). Each record is
    checked and recorded in history like any other, and the whole import is
    one event in Activity. A record whose parent or referenced record is in
    neither the bundle nor this project is skipped and named.
    """
    ctx = get_ctx()
    try:
        try:
            manifest = ctx.bundle_svc.inspect(bundle_file)
        except (NotFoundError, BundleError) as e:
            console.print(f"[error]{e}[/error]")
            raise typer.Exit(1)
        _print_manifest(manifest, bundle_file)
        if manifest.plugins:
            console.print(
                "[warning]This bundle carries plugins, which are code that runs "
                "with your workflows.[/warning]"
            )
        if not yes:
            typer.confirm("Import into this project?", abort=True)
        try:
            result = ctx.bundle_svc.import_bundle(bundle_file)
        except BundleError as e:
            console.print(f"[error]{e}[/error]")
            raise typer.Exit(1)
        ctx.commit()
    finally:
        ctx.close()
    _print_result(result)
    console.print("[success]Import complete.[/success]")


_ANY_ARGS = {"allow_extra_args": True, "ignore_unknown_options": True}


def dump_replaced(ctx: typer.Context) -> None:
    """Replaced by `civex bundle export`."""
    console.print(
        "[error]`civex dump` has been replaced by `civex bundle export`, which "
        "writes a bundle (a zip) that keeps record ids and can carry the files.[/error]"
    )
    raise typer.Exit(1)


def restore_replaced(ctx: typer.Context) -> None:
    """Replaced by `civex bundle import`."""
    console.print(
        "[error]`civex restore` has been replaced by `civex bundle import`. A YAML "
        "dump from an older civex can be read by that civex and exported again as "
        "a bundle.[/error]"
    )
    raise typer.Exit(1)
