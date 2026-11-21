"""`civex release`: frozen, citable copies of the project's data."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from civex.cli.bundle import _print_plan, _size
from civex.cli.utils import get_ctx
from civex.console import console
from civex.domain.dtos import ReleaseDTO
from civex.domain.exceptions import CivexError
from civex.services.release_service import ReleaseScope

app = typer.Typer(
    help=(
        "Freeze the data as a named, citable release (a bundle with a content "
        "hash and a citation), check it, cite it and see what changed since."
    ),
    no_args_is_help=True,
)


def _scope(collection: Optional[list[str]], query_json: Optional[str]) -> ReleaseScope:
    query = None
    if query_json:
        try:
            raw = json.loads(query_json)
        except json.JSONDecodeError as e:
            console.print(f"[error]--query-json is not JSON: {e}[/error]")
            raise typer.Exit(1)
        query = ReleaseScope.from_dict({"query": raw}).query
    return ReleaseScope(collections=collection or None, query=query)


def _describe_scope(scope: dict) -> str:
    if scope.get("collections"):
        return "Collections: " + ", ".join(scope["collections"])
    if scope.get("query"):
        return "Records listed by " + json.dumps(scope["query"])
    return "The whole project"


def _print_release(r: ReleaseDTO) -> None:
    table = Table(title=f"Release {r.name}", show_header=False, box=None)
    table.add_row("Title", r.title)
    if r.withdrawn_at:
        table.add_row(
            "[warning]Withdrawn[/warning]",
            f"{r.withdrawn_at:%Y-%m-%d} by {r.withdrawn_by or 'someone'}: "
            f"{r.withdrawn_reason}",
        )
    table.add_row("Authors", "; ".join(r.authors) or "none given")
    if r.description:
        table.add_row("Description", r.description)
    table.add_row("Licence", r.licence or "none given")
    table.add_row("DOI", r.doi or "none")
    table.add_row("Covers", _describe_scope(r.scope))
    counts = r.counts
    table.add_row(
        "Holds",
        f"{counts.get('records', 0)} records, {counts.get('schemas', 0)} schemas, "
        f"{counts.get('files_carried', 0)} files"
        + ("" if r.include_files else " (files not included)"),
    )
    table.add_row("Content hash", r.content_hash)
    table.add_row("Bundle", f"{r.bundle_sha256} ({_size(r.bundle_size)})")
    position = f"entry {r.local_seq}" if r.local_seq is not None else "not known here"
    if r.feed_seq is not None:
        position += f", server feed number {r.feed_seq}"
    table.add_row("History position", position)
    table.add_row(
        "Made",
        f"{r.created_at:%Y-%m-%d %H:%M} UTC by {r.created_by or 'unknown'}, "
        f"civex {r.civex_version}",
    )
    console.print(table)


def _fail(e: Exception) -> None:
    console.print(f"[error]{e}[/error]")
    raise typer.Exit(1)


@app.command("create")
def create(
    name: str = typer.Argument(..., help="The version, e.g. v1 or 2026-thesis"),
    title: str = typer.Option(..., "--title", "-t", help="What the data is"),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
    author: Optional[list[str]] = typer.Option(
        None, "--author", "-a", help="An author (repeatable, in citation order)"
    ),
    licence: Optional[str] = typer.Option(
        None, "--licence", "--license", help="e.g. CC-BY-4.0"
    ),
    doi: Optional[str] = typer.Option(None, "--doi", help="A DOI, if it has one"),
    collection: Optional[list[str]] = typer.Option(
        None,
        "--collection",
        "-c",
        help="Only these collections (repeatable); default the whole project",
    ),
    query_json: Optional[str] = typer.Option(
        None,
        "--query-json",
        help=(
            "Only the records a query lists (and the records above them), as "
            'JSON, e.g. {"dataset": "study", "schema": "sample"}'
        ),
    ),
    no_files: bool = typer.Option(
        False, "--no-files", help="Leave the stored files out (records still cite them)"
    ),
    no_workflows: bool = typer.Option(
        False, "--no-workflows", help="Leave workflows and plugins out"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Say what it would hold without making it"
    ),
) -> None:
    """Freeze the data as a release.

    Writes a bundle of the whole project, some collections or the records a
    query lists, hashes its contents, adds a CITATION.cff, and keeps it in the
    project's storage. A release never changes afterwards: its citation
    details can be corrected and it can be withdrawn, both recorded in
    history.
    """
    ctx = get_ctx()
    try:
        scope = _scope(collection, query_json)
        if dry_run:
            _print_plan(
                ctx.release_svc.plan(scope, not no_files, not no_workflows),
                f"Release {name} would hold",
            )
            return
        made = ctx.release_svc.create(
            name,
            title,
            scope,
            description=description,
            authors=author or [],
            licence=licence,
            doi=doi,
            include_files=not no_files,
            include_workflows=not no_workflows,
        )
        ctx.commit()
        _print_release(made)
        console.print(f"[success]Made release {made.name}[/success]")
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()


@app.command("list")
def list_releases() -> None:
    """List the project's releases, newest first."""
    ctx = get_ctx()
    try:
        releases = ctx.release_svc.list_all()
    finally:
        ctx.close()
    if not releases:
        console.print("No releases yet. Make one with `civex release create`.")
        return
    table = Table("Name", "Title", "Made", "Records", "Content hash", "")
    for r in releases:
        table.add_row(
            r.name,
            r.title,
            f"{r.created_at:%Y-%m-%d}",
            str(r.counts.get("records", 0)),
            r.content_hash[:19] + "…",
            "withdrawn" if r.withdrawn_at else "",
        )
    console.print(table)


@app.command("show")
def show(name: str = typer.Argument(..., help="The release's name or id")) -> None:
    """Show a release's citation details and manifest."""
    ctx = get_ctx()
    try:
        _print_release(ctx.release_svc.get(name))
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()


@app.command("verify")
def verify(name: str = typer.Argument(..., help="The release's name or id")) -> None:
    """Check the stored bundle still holds exactly what the release was made
    with: recompute its content hash, and every file's against its own."""
    ctx = get_ctx()
    try:
        result = ctx.release_svc.verify(name)
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()
    if result.matches:
        console.print(
            f"[success]Release {result.name} is intact: {result.actual}[/success]"
        )
        return
    console.print(f"[error]Release {result.name} does not match[/error]")
    console.print(f"  expected {result.expected}")
    console.print(f"  found    {result.actual or 'nothing'}")
    for problem in result.problems:
        console.print(f"  - {problem}")
    raise typer.Exit(1)


@app.command("withdraw")
def withdraw(
    name: str = typer.Argument(..., help="The release's name or id"),
    reason: str = typer.Option(..., "--reason", "-r", help="Why it is withdrawn"),
) -> None:
    """Mark a release withdrawn. It and its bundle are kept, so work that
    cited it can still be checked, and it says why wherever it is shown."""
    ctx = get_ctx()
    try:
        r = ctx.release_svc.withdraw(name, reason)
        ctx.commit()
        console.print(f"[success]Withdrew release {r.name}[/success]")
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()


@app.command("correct")
def correct(
    name: str = typer.Argument(..., help="The release's name or id"),
    title: Optional[str] = typer.Option(None, "--title", "-t"),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
    author: Optional[list[str]] = typer.Option(
        None, "--author", "-a", help="The authors, all of them (repeatable)"
    ),
    licence: Optional[str] = typer.Option(None, "--licence", "--license"),
    doi: Optional[str] = typer.Option(None, "--doi"),
) -> None:
    """Correct a release's citation details (a typo in the title, a DOI
    issued later). Its content never changes; the correction is in history."""
    values = {
        k: v
        for k, v in {
            "title": title,
            "description": description,
            "authors": author,
            "licence": licence,
            "doi": doi,
        }.items()
        if v is not None
    }
    ctx = get_ctx()
    try:
        r = ctx.release_svc.correct(name, **values)
        ctx.commit()
        _print_release(r)
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()


@app.command("cite")
def cite(
    name: str = typer.Argument(..., help="The release's name or id"),
    form: str = typer.Option(
        "text", "--format", "-f", help="text, bibtex or cff (CITATION.cff)"
    ),
) -> None:
    """Print how to cite a release."""
    ctx = get_ctx()
    try:
        text = ctx.release_svc.cite(name, form)
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()
    typer.echo(text.rstrip("\n"))


@app.command("diff")
def diff(name: str = typer.Argument(..., help="The release's name or id")) -> None:
    """Say what changed in the project since a release: records added,
    changed and deleted, per collection, from history."""
    ctx = get_ctx()
    try:
        since = ctx.release_svc.changes_since(name)
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()
    if not since.comparable:
        console.print(since.reason or "Can't compare here")
        return
    if not (since.added or since.changed or since.deleted or since.structure):
        console.print(f"Nothing has changed since release {since.name}.")
        return
    table = Table(
        "Collection", "Added", "Changed", "Deleted", title=f"Since {since.name}"
    )
    for c in since.collections:
        table.add_row(
            (c.collection or "(deleted)")
            + ("" if c.in_scope else " (not in the release)"),
            str(c.added),
            str(c.changed),
            str(c.deleted),
        )
    console.print(table)
    if since.structure:
        console.print(
            "Other changes: "
            + ", ".join(
                f"{n} to {kind}s" for kind, n in sorted(since.structure.items())
            )
        )


@app.command("download")
def download(
    name: str = typer.Argument(..., help="The release's name or id"),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Where to write it (default release-<name>.civex.zip)",
    ),
) -> None:
    """Write a release's bundle to a file. To get the data back as it was,
    read it into a new project with `civex bundle import`."""
    ctx = get_ctx()
    try:
        with ctx.release_svc.open_bundle(name) as (release, f):
            target = output or Path(ctx.release_svc.file_name_for(release.name))
            with target.open("wb") as out:
                shutil.copyfileobj(f, out, 1024 * 1024)
    except FileNotFoundError:
        _fail(Exception("The bundle is not on this computer and couldn't be fetched"))
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()
    console.print(f"[success]Wrote {target}[/success]")
