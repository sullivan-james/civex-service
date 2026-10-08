"""`civex sync library`: share workflows and plugins through the authority.

Publishing sends a file to the authority's library; installing writes one from
there into this project, after saying what it is. The work is in
LibraryService; these commands only ask for it and say what happened.
"""

from __future__ import annotations

import typer
from rich.markup import escape
from rich.syntax import Syntax
from rich.table import Table

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.exceptions import CivexError
from civex.domain.library import ABSENT, DIFFERENT, KINDS, OLDER, PLUGIN, SAME
from civex.domain.sync import SyncError

app = typer.Typer(
    help="Share workflows and plugins through the authority: publish them from "
    "here, install them from there. Nothing arrives by itself."
)

_HERE = {
    ABSENT: "not here",
    SAME: "installed",
    OLDER: "older here",
    DIFFERENT: "changed here",
}


def _here(item) -> str:  # noqa: ANN001 - LibraryItemDTO
    text = _HERE.get(item.here or "", "")
    if item.here == OLDER and item.local_version:
        text = f"v{item.local_version} here"
    return text


def _kind(kind: str) -> str:
    if kind not in KINDS:
        console.print("[error]Say workflow or plugin.[/error]")
        raise typer.Exit(1)
    return kind


def _fail(e: Exception) -> typer.Exit:
    console.print(f"[error]{escape(str(e))}[/error]")
    return typer.Exit(1)


@app.command("list")
def library_list() -> None:
    """What the library holds, and where each stands here."""
    c = _ctx()
    try:
        items = c.library_svc.browse()
    except (CivexError, SyncError) as e:
        raise _fail(e)
    finally:
        c.close()
    if not items:
        console.print("The library is empty.")
        return
    table = Table()
    for col in ("Kind", "Name", "Version", "Published by", "Here", "Notes"):
        table.add_column(col)
    for i in items:
        notes = []
        if i.provides:
            notes.append(f"provides {i.provides}")
        if i.needs:
            notes.append(f"uses {', '.join(i.needs)}")
        if i.triggers:
            notes.append(f"runs on {'; '.join(i.triggers)}")
        if i.missing:
            notes.append(f"[warning]needs {', '.join(i.missing)} (nowhere)[/warning]")
        table.add_row(
            i.kind,
            i.name,
            f"v{i.version}" + (f" ({len(i.history)})" if len(i.history) > 1 else ""),
            i.published_by or "",
            _here(i),
            escape("; ".join(notes)) if not i.missing else "; ".join(notes),
        )
    console.print(table)


@app.command("show")
def library_show(
    kind: str = typer.Argument(help="workflow or plugin."),
    name: str = typer.Argument(help="Its name in the library."),
    version: int = typer.Option(None, "--version", "-v", help="Default: the newest."),
) -> None:
    """Print a shared workflow or plugin and its versions, to read it first."""
    c = _ctx()
    try:
        item = c.library_svc.show(_kind(kind), name, version)
    except (CivexError, SyncError) as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(
        f"[bold]{escape(item.filename)}[/bold]  version {item.version}, published by "
        f"{escape(item.published_by or 'unknown')} at {item.published_at}  "
        f"[dim]sha256 {item.sha256}[/dim]  ({_here(item)})"
    )
    for pid, pinned in sorted(item.pins.items()):
        console.print(f"  uses {escape(pid)} v{pinned}")
    if len(item.history) > 1:
        console.print(
            "  versions: "
            + ", ".join(
                f"v{h['version']}"
                + (" (here)" if h["version"] == item.local_version else "")
                for h in item.history
            )
        )
    lexer = "python" if item.kind == PLUGIN else "yaml"
    console.print(Syntax(item.content or "", lexer, line_numbers=True))


@app.command("publish")
def library_publish(
    kind: str = typer.Argument(help="workflow or plugin."),
    name: str = typer.Argument(help="The workflow's or plugin file's name here."),
    without_plugins: bool = typer.Option(
        False,
        "--without-plugins",
        help="Send the workflow alone: the plugins it uses must be in the library.",
    ),
) -> None:
    """Publish a workflow (with the plugins its steps use) or a plugin."""
    c = _ctx()
    try:
        result = c.library_svc.publish(_kind(kind), name, not without_plugins)
        c.commit()
    except (CivexError, SyncError) as e:
        raise _fail(e)
    finally:
        c.close()
    for i in result.items:
        console.print(f"Published {escape(i.filename)} (version {i.version}).")
    for warning in result.warnings:
        console.print(f"[warning]{escape(warning)}[/warning]")


@app.command("install")
def library_install(
    kind: str = typer.Argument(help="workflow or plugin."),
    name: str = typer.Argument(help="Its name in the library."),
    version: int = typer.Option(
        None, "--version", "-v", help="Default: the newest. An earlier one rolls back."
    ),
    without_plugins: bool = typer.Option(
        False, "--without-plugins", help="Install the workflow alone."
    ),
    replace: bool = typer.Option(
        False, "--replace", help="Replace files that were changed here."
    ),
    force: bool = typer.Option(
        False, "--force", help="Install even though it breaks workflows here."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask first."),
) -> None:
    """Install from the library into this project, after saying what it writes.

    A workflow brings the plugin versions it was published with. Nothing that
    would break a workflow here is installed unless you say --force. A plugin is
    code: once installed it runs on this computer, as you.
    """
    kind = _kind(kind)
    args = (kind, name, version, not without_plugins, replace, force)
    c = _ctx()
    try:
        plan = c.library_svc.plan_install(*args)
        for step in plan.steps:
            i = step.item
            if step.here == SAME:
                state = "unchanged"
            elif step.local_version:
                state = f"v{step.local_version} → v{i.version}"
            elif step.here == DIFFERENT:
                state = "replaces yours"
            else:
                state = "new"
            console.print(
                f"  {escape(step.path)}  [dim]{state}; v{i.version} by "
                f"{escape(i.published_by or 'unknown')}; sha256 {i.sha256[:12]}…[/dim]"
            )
        for warning in plan.warnings:
            console.print(f"  [warning]{escape(warning)}[/warning]")
        for broken in plan.breaks:
            console.print(f"  [error]breaks {escape(broken)}[/error]")
        if plan.blocked:
            raise _fail(ValueError(" ".join(plan.blocked)))
        if plan.nothing_to_do:
            console.print("Already installed.")
            return
        if plan.runs_code:
            console.print(
                "[warning]This installs plugin code that will run on this computer "
                "with your permissions. Read it first with `civex sync library show "
                "plugin <name>`.[/warning]"
            )
        if not yes and not typer.confirm("Install?"):
            raise typer.Exit(1)
        done = c.library_svc.install(*args)
    except (CivexError, SyncError) as e:
        raise _fail(e)
    finally:
        c.close()
    for warning in done.warnings:
        if warning not in plan.warnings:
            console.print(f"[warning]{escape(warning)}[/warning]")
    console.print("Installed.")


@app.command("remove")
def library_remove(
    kind: str = typer.Argument(help="workflow or plugin."),
    name: str = typer.Argument(help="Its name in the library."),
    version: int = typer.Option(
        None, "--version", "-v", help="One version; default: every version."
    ),
    force: bool = typer.Option(
        False, "--force", help="Even if shared workflows are pinned to it."
    ),
) -> None:
    """Take something out of the library. Copies already installed stay."""
    c = _ctx()
    try:
        c.library_svc.unpublish(_kind(kind), name, version, force)
        c.commit()
    except (CivexError, SyncError) as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(f"Removed {escape(name)} from the library.")
