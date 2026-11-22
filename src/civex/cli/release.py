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
from civex.services.release_service import ReleasePlan, ReleaseScope

app = typer.Typer(
    help=(
        "Freeze the data as a named, citable release (its records with a "
        "content hash and a citation; the files stay where they are and the "
        "release keeps them), check it, cite it, get its files out, see what "
        "changed since, and withdraw or yank it."
    ),
    no_args_is_help=True,
)


def _scope(
    collection: Optional[list[str]],
    query_json: Optional[str],
    record: Optional[list[str]] = None,
    only_chosen: bool = False,
) -> ReleaseScope:
    query = None
    if query_json:
        try:
            raw = json.loads(query_json)
        except json.JSONDecodeError as e:
            console.print(f"[error]--query-json is not JSON: {e}[/error]")
            raise typer.Exit(1)
        query = ReleaseScope.from_dict({"query": raw}).query
    return ReleaseScope(
        collections=collection or None,
        query=query,
        records=record or None,
        # Chosen records come with everything inside them, unless told not to.
        below=bool(query or record) and not only_chosen,
    )


def _authors(raw: Optional[list[str]]) -> list[dict[str, str]] | None:
    """`Name`, or `Name|ORCID|Affiliation` (either part may be left empty)."""
    if raw is None:
        return None
    out = []
    for text in raw:
        name, _, rest = text.partition("|")
        orcid, _, affiliation = rest.partition("|")
        out.append({"name": name, "orcid": orcid, "affiliation": affiliation})
    return out


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


def _print_plan(plan: ReleasePlan, title: str) -> None:
    table = Table(title=title, show_header=False, box=None)
    table.add_row("Records", str(plan.records))
    for name, n in plan.collections.items():
        table.add_row("", f"{name}: {n}")
    table.add_row("Schemas", str(plan.schemas))
    table.add_row(
        "Files",
        f"{plan.files} ({_size(plan.file_bytes)}), kept where they are",
    )
    for d in plan.by_drive:
        table.add_row("", f"{d['volume'] or 'not on this computer'}: {d['files']}")
    table.add_row("Workflows", f"{plan.workflows} workflows, {plan.plugins} plugins")
    position = f"entry {plan.local_seq}"
    if plan.feed_seq is not None:
        position += f", server feed number {plan.feed_seq}"
    table.add_row("History position", position)
    if plan.unsent:
        table.add_row("[warning]Unsent[/warning]", f"{plan.unsent} changes: sync first")
    console.print(table)


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


@app.command("create")
def create(
    name: str = typer.Argument(..., help="The version, e.g. v1 or 2026-thesis"),
    title: str = typer.Option(..., "--title", "-t", help="What the data is"),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="A longer account of the data"
    ),
    author: Optional[list[str]] = typer.Option(
        None,
        "--author",
        "-a",
        help="An author, as Name or Name|ORCID|Affiliation (repeatable, in citation order)",
    ),
    licence: Optional[str] = typer.Option(
        None, "--licence", "--license", help="An SPDX id, e.g. CC-BY-4.0"
    ),
    doi: Optional[str] = typer.Option(None, "--doi", help="A DOI, if it has one"),
    keyword: Optional[list[str]] = typer.Option(
        None, "--keyword", "-k", help="A keyword (repeatable)"
    ),
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
    record: Optional[list[str]] = typer.Option(
        None, "--record", "-r", help="Exactly these records, by id (repeatable)"
    ),
    only_chosen: bool = typer.Option(
        False,
        "--only-chosen",
        help="With --record or --query-json: leave out the records inside the "
        "ones chosen (they are taken by default)",
    ),
    no_workflows: bool = typer.Option(
        False, "--no-workflows", help="Leave workflows and plugins out"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Say what it would hold without making it"
    ),
) -> None:
    """Freeze the data as a release.

    Writes the records of the whole project, some collections, the records
    a query lists or chosen records into a small bundle, hashes it (each cited
    file by its hash, so no file is read), adds a CITATION.cff, and keeps it
    in the project's storage. The files stay where they are: the release
    keeps them, so a clean-up never removes them. A release never changes
    afterwards: its citation details can be corrected, and it can be
    withdrawn or yanked, each recorded in history.
    """
    ctx = get_ctx()
    try:
        scope = _scope(collection, query_json, record, only_chosen)
        if dry_run:
            _print_plan(
                ctx.release_svc.plan(scope, not no_workflows),
                f"Release {name} would hold",
            )
            return
        made = ctx.release_svc.create(
            name,
            title,
            scope,
            description=description,
            authors=_authors(author) or [],
            licence=licence,
            doi=doi,
            keywords=keyword or [],
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


@app.command("withdraw")
def withdraw(
    name: str = typer.Argument(..., help="The release's name or id"),
    reason: str = typer.Option(..., "--reason", "-r", help="Why it is withdrawn"),
) -> None:
    """Mark a release withdrawn. It keeps its data, so work that cited it can
    still be checked, and it says why wherever it is shown. To give the data
    up, yank it."""
    ctx = get_ctx()
    try:
        r = ctx.release_svc.withdraw(name, reason)
        ctx.commit()
        console.print(f"[success]Withdrew release {r.name}[/success]")
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()


@app.command("yank")
def yank(
    name: str = typer.Argument(..., help="The release's name or id"),
    reason: str = typer.Option(..., "--reason", "-r", help="Why its data goes"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask to confirm"),
) -> None:
    """Give a release's data up for good. It stops keeping its files and its
    bundle, so the next clean-up removes whatever nothing else uses; what is
    left is a record of it that a citation still finds. Says first how much
    would go. Can't be undone."""
    ctx = get_ctx()
    try:
        plan = ctx.release_svc.plan_yank(name)
        console.print(
            f"Yanking {plan.name} gives up {plan.files} files: {plan.unused_files} "
            f"({_size(plan.unused_bytes)}) are used by nothing else and a clean-up "
            f"then removes them; {plan.kept_files} stay for their other users."
        )
        if not yes and not typer.confirm("Yank it? This can't be undone"):
            raise typer.Exit(1)
        r = ctx.release_svc.yank(name, reason)
        ctx.commit()
        console.print(f"[success]Yanked release {r.name}[/success]")
    except CivexError as e:
        _fail(e)
    finally:
        ctx.close()


@app.command("export")
def export(
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
    release.json and CITATION.cff beside them."""
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


@app.command("correct")
def correct(
    name: str = typer.Argument(..., help="The release's name or id"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="The new title"),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="A longer account of the data"
    ),
    author: Optional[list[str]] = typer.Option(
        None,
        "--author",
        "-a",
        help="The authors, all of them, as Name or Name|ORCID|Affiliation (repeatable)",
    ),
    licence: Optional[str] = typer.Option(
        None, "--licence", "--license", help="An SPDX id (e.g. CC-BY-4.0) or a name"
    ),
    doi: Optional[str] = typer.Option(None, "--doi", help="The DOI it was given"),
    keyword: Optional[list[str]] = typer.Option(
        None, "--keyword", "-k", help="The keywords, all of them (repeatable)"
    ),
) -> None:
    """Correct a release's citation details (a typo in the title, a DOI
    issued later). Its content never changes; the correction is in history."""
    values = {
        k: v
        for k, v in {
            "title": title,
            "description": description,
            "authors": _authors(author),
            "licence": licence,
            "doi": doi,
            "keywords": keyword,
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
