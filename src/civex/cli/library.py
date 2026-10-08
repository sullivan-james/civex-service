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
from civex.domain.library import ABSENT, DIFFERENT, KINDS, PLUGIN, SAME
from civex.domain.sync import SyncError

app = typer.Typer(
    help="Share workflows and plugins through the authority: publish them from "
    "here, install them from there. Nothing arrives by itself."
)

_HERE = {ABSENT: "not here", SAME: "installed", DIFFERENT: "differs here"}


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
            str(i.version),
            i.published_by or "",
            _HERE.get(i.here or "", ""),
            escape("; ".join(notes)) if not i.missing else "; ".join(notes),
        )
    console.print(table)


@app.command("show")
def library_show(
    kind: str = typer.Argument(help="workflow or plugin."),
    name: str = typer.Argument(help="Its name in the library."),
) -> None:
    """Print a shared workflow or plugin, to read it before installing."""
    c = _ctx()
    try:
        item = c.library_svc.show(_kind(kind), name)
    except (CivexError, SyncError) as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(
        f"[bold]{escape(item.filename)}[/bold]  version {item.version}, published by "
        f"{escape(item.published_by or 'unknown')} at {item.published_at}  "
        f"[dim]sha256 {item.sha256}[/dim]  ({_HERE.get(item.here or '', '')})"
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
        items = c.library_svc.publish(_kind(kind), name, not without_plugins)
        c.commit()
    except (CivexError, SyncError) as e:
        raise _fail(e)
    finally:
        c.close()
    for i in items:
        console.print(f"Published {escape(i.filename)} (version {i.version}).")


@app.command("install")
def library_install(
    kind: str = typer.Argument(help="workflow or plugin."),
    name: str = typer.Argument(help="Its name in the library."),
    without_plugins: bool = typer.Option(
        False, "--without-plugins", help="Install the workflow alone."
    ),
    replace: bool = typer.Option(
        False, "--replace", help="Replace files here whose contents differ."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask first."),
) -> None:
    """Install from the library into this project, after saying what it writes.

    A plugin is code: once installed it runs on this computer, as you.
    """
    kind = _kind(kind)
    c = _ctx()
    try:
        plan = c.library_svc.plan_install(kind, name, not without_plugins, replace)
        for step in plan.steps:
            i = step.item
            state = (
                "unchanged"
                if step.here == SAME
                else ("replaces yours" if step.here == DIFFERENT else "new")
            )
            console.print(
                f"  {escape(step.path)}  [dim]{state}; v{i.version} by "
                f"{escape(i.published_by or 'unknown')}; sha256 {i.sha256[:12]}…[/dim]"
            )
        for warning in plan.warnings:
            console.print(f"  [warning]{escape(warning)}[/warning]")
        if plan.blocked:
            raise _fail(ValueError(" ".join(plan.blocked)))
        if all(s.here == SAME for s in plan.steps):
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
        done = c.library_svc.install(kind, name, not without_plugins, replace)
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
    force: bool = typer.Option(
        False, "--force", help="Remove a plugin even if shared workflows use it."
    ),
) -> None:
    """Take something out of the library. Copies already installed stay."""
    c = _ctx()
    try:
        c.library_svc.unpublish(_kind(kind), name, force)
        c.commit()
    except (CivexError, SyncError) as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(f"Removed {escape(name)} from the library.")
