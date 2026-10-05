"""`civex sync`: follow an authority, and (on the machine that is one) issue
device tokens. The work is in SyncService / SyncAuthorityService; these commands
only ask for it and say what happened."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import typer
from rich.markup import escape
from rich.table import Table

from civex.cli.utils import cli_load_config, get_ctx as _ctx
from civex.config import save_config
from civex.console import console
from civex.domain.exceptions import CivexError
from civex.domain.sync import SyncError

app = typer.Typer(
    help="Keep this project in step with an authority: another civex that holds "
    "the project's shared copy.",
    invoke_without_command=True,
)
authority_app = typer.Typer(help="Act as the authority for this project.")
device_app = typer.Typer(help="Devices allowed to follow this authority.")
app.add_typer(authority_app, name="authority")
app.add_typer(device_app, name="device")


def _fail(e: Exception) -> typer.Exit:
    console.print(f"[error]{escape(str(e))}[/error]")
    return typer.Exit(1)


def _describe(report) -> None:  # noqa: ANN001 — SyncReport
    console.print(
        f"Received {report.pulled}, sent {report.pushed}"
        + (f", files sent {report.files_sent}" if report.files_sent else "")
    )
    if report.conflicts:
        console.print(
            f"[warning]{report.conflicts} value(s) did not go in as made; "
            "see `civex sync conflicts`.[/warning]"
        )
    if report.rejected:
        console.print(f"[warning]{report.rejected} change(s) were refused.[/warning]")
    if report.waiting:
        console.print(
            f"[dim]{report.waiting} change(s) are waiting for a file; they go on the next sync.[/dim]"
        )


@app.callback()
def _default(ctx: typer.Context) -> None:
    """Run a sync now when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        now()


@app.command("now")
def now() -> None:
    """Send this project's changes and bring in everyone else's."""
    c = _ctx()
    try:
        if not c.sync_svc.configured:
            console.print(
                "[error]No authority is set. Use `civex sync connect`.[/error]"
            )
            raise typer.Exit(1)
        _describe(c.sync_svc.sync())
    except (SyncError, CivexError) as e:
        raise _fail(e)
    finally:
        c.close()


@app.command("watch")
def watch() -> None:
    """Keep syncing in this terminal until stopped (Ctrl+C): after edits, on the
    interval, and backing off when the authority can't be reached."""
    import threading

    from civex.context import build_local_context
    from civex.services.sync_worker import SyncWorker

    config = cli_load_config()
    if not config.sync.remote:
        console.print("[error]No authority is set. Use `civex sync connect`.[/error]")
        raise typer.Exit(1)
    console.print(f"Syncing with {config.sync.remote} (Ctrl+C to stop).")
    stop = threading.Event()
    worker = SyncWorker(cli_load_config, build_local_context)
    try:
        worker.run(stop)
    except KeyboardInterrupt:
        stop.set()


@app.command("status")
def status() -> None:
    """Show where this project stands with its authority."""
    c = _ctx()
    try:
        s = c.sync_svc.status()
    finally:
        c.close()
    if not s.configured:
        console.print("Not following an authority.")
        return
    console.print(f"Authority   {s.remote}")
    console.print(f"Project     {s.project_id}")
    console.print(f"Paused      {'yes' if s.paused else 'no'}")
    console.print(f"Unsent      {s.pending}")
    console.print(f"Conflicts   {s.open_conflicts}")
    console.print(f"Last synced {s.last_synced_at or 'never'}")
    if s.last_error:
        console.print(f"[warning]Last problem  {escape(s.last_error)}[/warning]")


@app.command("connect")
def connect(
    url: str = typer.Argument(
        help="The authority's address, e.g. https://civex.example.com"
    ),
    token: str = typer.Option(
        ...,
        "--token",
        envvar="CIVEX_SYNC_TOKEN",
        help="The device token the authority issued.",
    ),
) -> None:
    """Point this project at an authority. An empty project becomes a copy of
    it; a project with data fills an empty authority. Two projects that both
    hold data are refused."""
    c = _ctx()
    try:
        mode = c.sync_svc.connect(url, token)
        c.commit()
    except (SyncError, CivexError) as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(f"[success]Connected ({mode}).[/success]")


@app.command("disconnect")
def disconnect() -> None:
    """Stop following the authority. The data here stays as it is."""
    c = _ctx()
    try:
        c.sync_svc.disconnect()
        c.commit()
    finally:
        c.close()
    console.print("Disconnected.")


@app.command("pause")
def pause() -> None:
    """Stop syncing until resumed. Changes keep being recorded."""
    c = _ctx()
    try:
        c.sync_svc.set_paused(True)
    finally:
        c.close()
    console.print("Sync paused.")


@app.command("resume")
def resume() -> None:
    """Start syncing again."""
    c = _ctx()
    try:
        c.sync_svc.set_paused(False)
    finally:
        c.close()
    console.print("Sync resumed.")


@app.command("conflicts")
def conflicts(
    all_: bool = typer.Option(False, "--all", help="Include ones already settled."),
) -> None:
    """List values that did not go in as made, with both sides."""
    c = _ctx()
    try:
        found = c.sync_svc.conflicts(None if all_ else "open")
    finally:
        c.close()
    if not found:
        console.print("No conflicts.")
        return
    table = Table()
    for col in ("Id", "What", "Field", "Yours", "Theirs", "State"):
        table.add_column(col)
    for f in found:
        table.add_row(
            str(f.id),
            f"{f.entity_type} {str(f.entity_id)[:8]}",
            f.field or "",
            escape(str(f.yours)),
            escape(str(f.theirs)),
            f.resolution or f.status,
        )
    console.print(table)


@app.command("resolve")
def resolve(
    conflict_id: str = typer.Argument(help="The conflict's id."),
    take: str = typer.Option(
        ...,
        "--take",
        help="'theirs' keeps the authority's value; 'mine' makes yours a new change.",
    ),
) -> None:
    """Settle a conflict."""
    try:
        cid = uuid.UUID(conflict_id)
    except ValueError:
        raise _fail(ValueError("That is not a conflict id"))
    c = _ctx()
    try:
        c.sync_svc.resolve_conflict(cid, take)
    except CivexError as e:
        raise _fail(e)
    finally:
        c.close()
    console.print("Settled.")


@authority_app.command("enable")
def authority_enable() -> None:
    """Let devices with a token follow this project (serve it with `civex serve`)."""
    config = cli_load_config()
    config.sync.serve = True
    save_config(config)
    console.print(
        "This project now accepts devices. Issue one a token with "
        "`civex sync device add <name>`."
    )


@authority_app.command("disable")
def authority_disable() -> None:
    """Stop accepting devices. Their tokens stay on record."""
    config = cli_load_config()
    config.sync.serve = False
    save_config(config)
    console.print("This project no longer accepts devices.")


@device_app.command("add")
def device_add(name: str = typer.Argument(help="What to call the device.")) -> None:
    """Issue a device a token. It is shown once and cannot be read back."""
    c = _ctx()
    try:
        _, token = c.authority_svc.add_device(name)
        c.commit()
    except CivexError as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(f"Token for {escape(name)} (shown once):\n\n  {token}\n")


@device_app.command("list")
def device_list() -> None:
    """List the devices that have been issued a token."""
    c = _ctx()
    try:
        devices = c.authority_svc.list_devices()
    finally:
        c.close()
    table = Table()
    for col in ("Name", "Created", "Last seen", "State"):
        table.add_column(col)
    for d in devices:
        table.add_row(
            d.name,
            d.created_at,
            d.last_seen_at or "never",
            "revoked" if d.revoked_at else "active",
        )
    console.print(table)


@device_app.command("revoke")
def device_revoke(name: str = typer.Argument(help="The device's name.")) -> None:
    """Stop a device's token working."""
    c = _ctx()
    try:
        ok = c.authority_svc.revoke_device(name)
        c.commit()
    finally:
        c.close()
    if not ok:
        raise _fail(ValueError(f"No active device named {name}"))
    console.print(f"Revoked {escape(name)}.")


def clone(
    url: str = typer.Argument(help="The authority's address."),
    path: Path = typer.Argument(
        None, help="Where to put the copy (default: a new folder here)."
    ),
    token: str = typer.Option(
        ...,
        "--token",
        envvar="CIVEX_SYNC_TOKEN",
        help="The device token the authority issued.",
    ),
) -> None:
    """Make a new project that is a copy of an authority's, and keep it in step."""
    from civex.cli.init import _init_working

    target = (
        path or Path(url.rstrip("/").rsplit("/", 1)[-1] or "civex-project")
    ).resolve()
    target.mkdir(parents=True, exist_ok=True)
    _init_working(target, use_sqlite=True)
    os.chdir(target)
    c = _ctx()
    try:
        c.sync_svc.connect(url, token)
        c.commit()
    except (SyncError, CivexError) as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(f"[success]Cloned into {target}.[/success]")
