"""`civex release`: frozen, citable copies of the project's data."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from civex.cli.bundle import _size
from civex.cli.utils import get_ctx
from civex.console import console
from civex.domain.dtos import ReleaseDTO
from civex.domain.exceptions import CivexError

HUB_ONLY = "Releases are published on a civex hub."

app = typer.Typer(
    help=(
        "Releases are published on a civex hub, not made here. A release already "
        "on this computer stays readable: list it, check it, cite it, compare "
        "it with the data now, and export it as a bundle."
    ),
    invoke_without_command=True,
)


@app.callback()
def _hub_only(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(
            f"{HUB_ONLY} Releases already on this computer can still be read: "
            "`civex release list`, and `civex release export NAME` writes one "
            "as a bundle."
        )


def _describe_scope(scope: dict) -> str:
    if scope.get("collections"):
        return "Collections: " + ", ".join(scope["collections"])
    if scope.get("records"):
        return f"{len(scope['records'])} chosen records" + (
            " and what is inside them" if scope.get("below") else ""
        )
    if scope.get("query"):
        return "Records listed by " + json.dumps(scope["query"])
    return "The whole project"


def _author_text(a: dict) -> str:
    extra = ", ".join(x for x in (a.get("orcid"), a.get("affiliation")) if x)
    return a["name"] + (f" ({extra})" if extra else "")


class _Bar:
    """A Rich bar standing in for `services.progress.Progress`."""

    def __init__(self, bar, task) -> None:
        self._bar, self._task = bar, task

    def phase(self, label: str, total: int = 0, total_bytes: int = 0) -> None:
        self._bar.reset(self._task, total=total or None, description=label)

    def advance(self, done: int) -> None:
        self._bar.update(self._task, completed=done)


def _print_release(r: ReleaseDTO) -> None:
    table = Table(title=f"Release {r.name}", show_header=False, box=None)
    table.add_row("Title", r.title)
    if r.yanked_at:
        table.add_row(
            "[error]Yanked[/error]",
            f"{r.yanked_at:%Y-%m-%d} by {r.yanked_by or 'someone'}: "
            f"{r.yanked_reason} (its data was given up)",
        )
    elif r.withdrawn_at:
        table.add_row(
            "[warning]Withdrawn[/warning]",
            f"{r.withdrawn_at:%Y-%m-%d} by {r.withdrawn_by or 'someone'}: "
            f"{r.withdrawn_reason}",
        )
    table.add_row(
        "Authors", "; ".join(_author_text(a) for a in r.authors) or "none given"
    )
    if r.description:
        table.add_row("Description", r.description)
    table.add_row("Licence", r.licence or "none given")
    table.add_row("DOI", r.doi or "none")
    if r.keywords:
        table.add_row("Keywords", ", ".join(r.keywords))
    table.add_row("Covers", _describe_scope(r.scope))
    counts = r.counts
    table.add_row(
        "Holds",
        f"{counts.get('records', 0)} records, {counts.get('schemas', 0)} schemas, "
        f"{counts.get('files', 0)} files ({_size(counts.get('file_bytes', 0))})",
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
            "yanked" if r.yanked_at else "withdrawn" if r.withdrawn_at else "",
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
def verify(
    name: str = typer.Argument(..., help="The release's name or id"),
    deep: bool = typer.Option(
        False,
        "--deep",
        help="Also read every file back against its hash (long, for a large release)",
    ),
) -> None:
    """Check a release still holds exactly what it was made with: its records'
    content hash, and every file it cites recorded on a drive here. With
    --deep, every file is read back against its hash too."""
    from rich.progress import BarColumn, Progress, TextColumn

    ctx = get_ctx()
    try:
        if deep:
            with Progress(
                TextColumn("{task.description}"), BarColumn(), console=console
            ) as bar:
                shim = _Bar(bar, bar.add_task("Checking", total=None))
                result = ctx.release_svc.verify(name, deep=True, progress=shim)  # type: ignore[arg-type]
            ctx.commit()
        else:
            result = ctx.release_svc.verify(name)
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()
    for note in result.notes:
        console.print(f"  {note}")
    if result.matches:
        console.print(
            f"[success]Release {result.name} is intact: {result.actual} "
            f"({result.files} files"
            + (f", {result.files_read} read back" if result.deep else "")
            + ")[/success]"
        )
        return
    console.print(f"[error]Release {result.name} does not match[/error]")
    console.print(f"  expected {result.expected}")
    console.print(f"  found    {result.actual or 'nothing'}")
    for problem in result.problems:
        console.print(f"  - {problem}")
    raise typer.Exit(1)


@app.command("export")
def export(
    name: str = typer.Argument(..., help="The release's name or id"),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Where to write it (default release-<name>.civex.zip)",
    ),
) -> None:
    """Write a release as one bundle, with its files, so nobody loses a release
    made on this computer. Read it into a new project with `civex bundle
    import`. A file that can't be reached is named in the bundle and left out."""
    ctx = get_ctx()
    try:
        target = output or Path(
            ctx.release_svc.file_name_for(ctx.release_svc.get(name).name)
        )
        release = ctx.release_svc.write_full_bundle(name, target)
    except FileNotFoundError:
        _fail(Exception("The bundle is not on this computer and couldn't be fetched"))
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()
    console.print(f"[success]Wrote release {release.name} to {target}[/success]")


@app.command("files")
def files(
    name: str = typer.Argument(..., help="The release's name or id"),
    mode: str = typer.Option(
        "link",
        "--mode",
        help="link: a folder on the drive holding most of the files; copy: copies on --volume",
    ),
    volume: Optional[str] = typer.Option(None, "--volume", help="Where copies go"),
    folder: Optional[str] = typer.Option(None, "--name", help="The folder's name"),
    partial: bool = typer.Option(
        False, "--partial", help="Make it with what can be reached"
    ),
) -> None:
    """Make a folder of a release's files, laid out like any export (a folder
    per record), with manifest-sha256.txt (each file's hash and path),
    release.json and CITATION.cff beside them. To take the whole release with
    you, as one file, use `civex release export`."""
    from civex.domain.file_access import FilesUnavailableError

    ctx = get_ctx()
    try:
        with ctx.release_svc.file_access(name) as (access, selection):
            result = access.export_managed(
                selection,
                folder or f"release-{name}",
                mode,
                volume,
                allow_partial=partial,
            )
            plan = access.plan(selection)
        ctx.release_svc.write_bag(name, Path(result.dest), plan)
    except FilesUnavailableError as e:
        console.print(f"[error]{e}[/error]")
        for group in e.plan.unavailable:
            console.print(
                f"  {group.volume or 'nowhere'}: {group.files} files. {group.fix}"
            )
        raise typer.Exit(1)
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()
    console.print(f"[success]Made {result.dest}[/success]")


@app.command("gather")
def gather(
    name: str = typer.Argument(..., help="The release's name or id"),
    to: str = typer.Option(..., "--to", help="The drive to put its files on"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Say what would move"),
) -> None:
    """Put a release's files on one drive, as any move does (Ctrl+C pauses).
    Only the release's own copies move: a copy its records use elsewhere is
    copied, not moved."""
    from civex.cli.transfers import _start

    ctx = get_ctx()
    try:
        spec = ctx.release_svc.gather_spec(name, to)
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()
    _start(spec, dry_run)


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
def diff(
    name: str = typer.Argument(..., help="The release's name or id"),
    show: Optional[str] = typer.Option(
        None,
        "--show",
        help="List the records one kind of difference means: added, changed or removed",
    ),
) -> None:
    """Compare a release with the data now, record by record: records added
    to its scope, changed and removed, per collection, and the schemas and
    fields changed since. Worked out from the data, not from history, so
    every computer gives the same answer."""
    from rich.progress import BarColumn, Progress, TextColumn

    ctx = get_ctx()
    try:
        release = ctx.release_svc.get(name)
        if ctx.release_svc.in_background(release):
            with Progress(
                TextColumn("{task.description}"), BarColumn(), console=console
            ) as bar:
                shim = _Bar(bar, bar.add_task("Comparing", total=None))
                result = ctx.release_svc.compare(name, shim)  # type: ignore[arg-type]
        else:
            result = ctx.release_svc.compare(name)
        listed = ctx.release_svc.compared_records(name, show, 0, 500) if show else None
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()
    if listed is not None:
        total, items = listed
        for item in items:
            console.print(
                f"{item['id']}  {item['collection'] or ''}  {item['schema'] or ''}  "
                f"{item['name'] or ''}"
            )
        if total > len(items):
            console.print(f"… and {total - len(items)} more")
        return
    if not (result.added or result.changed or result.removed or result.structure):
        console.print(
            f"Nothing has changed since release {result.name} "
            f"({result.records} records)."
        )
        return
    table = Table(
        "Collection", "Added", "Changed", "Removed", title=f"Since {result.name}"
    )
    for c in result.collections:
        table.add_row(
            (c.collection or "(gone)")
            + ("" if c.in_scope else " (not in the release)"),
            str(c.added),
            str(c.changed),
            str(c.removed),
        )
    console.print(table)
    console.print(f"{result.unchanged} of its {result.records} records are unchanged.")
    for s in result.structure:
        where = f" of {s['schema']}" if s.get("schema") else ""
        what = f" ({', '.join(s['what'])})" if s.get("what") else ""
        console.print(f"  {s['kind']} {s['name']}{where} {s['change']}{what}")


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
    """Write a release's bundle of records to a file. To get the records back
    as they were, read it into a new project with `civex bundle import`; its
    files come out with `civex release export`."""
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
