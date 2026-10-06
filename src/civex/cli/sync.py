"""`civex sync`: follow an authority, and (on the machine that is one) issue
device tokens. The work is in SyncService / SyncAuthorityService; these commands
only ask for it and say what happened."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import typer
from rich.markup import escape
from rich.table import Table

from civex.cli.utils import cli_load_config, get_ctx as _ctx
from civex.console import console
from civex.domain.exceptions import CivexError
from civex.domain.sync import COPYING, FILLING, SyncError, SyncProgress

app = typer.Typer(
    help="Keep this project in step with an authority: another civex that holds "
    "the project's shared copy.",
    invoke_without_command=True,
)
authority_app = typer.Typer(help="Act as the authority for this project.")
device_app = typer.Typer(help="Devices allowed to follow this authority.")
app.add_typer(authority_app, name="authority")
app.add_typer(device_app, name="device")


_PHASES = {
    COPYING: "Copying from the server",
    FILLING: "Filling the server",
}
_KINDS = {"dataset": "collections"}


def _connect_showing_progress(c, url: str, token: str | None) -> str:
    """Connect, with a live bar while things are copied either way, then fetch
    the history from before joining with a bar of its own. Stopping that part
    (Ctrl+C) loses nothing: the project is already usable, and whatever syncs
    it next (the server, `civex sync watch`) carries on from where it got to."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    columns = (
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    )
    with Progress(*columns, console=console, transient=True) as bar:
        task = bar.add_task("Connecting", total=None)

        def show(p: SyncProgress) -> None:
            kind = _KINDS.get(p.kind or "", f"{p.kind}s" if p.kind else "")
            label = _PHASES.get(p.phase, p.phase)
            bar.update(
                task,
                description=f"{label}  {kind}".rstrip(),
                completed=p.done,
                total=p.total,
            )

        mode = c.sync_svc.connect(url, token, progress=show)
        c.commit()
    if mode == "joined":
        _fetch_history_showing_progress(c)
    return mode


def _fetch_history_showing_progress(c) -> None:
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=True,
    ) as bar:
        task = bar.add_task("Fetching history (Ctrl+C to leave it to run later)")
        try:
            c.sync_svc.fetch_history(
                lambda p: bar.update(task, completed=p.done, total=p.total)
            )
        except KeyboardInterrupt:
            console.print(
                "History from before joining will carry on arriving the next time "
                "this project syncs."
            )
        except SyncError as e:
            console.print(
                f"[warning]History not fetched yet: {escape(str(e))}[/warning]"
            )


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


@app.command("user")
def user(
    name: str = typer.Argument(None, help="The name to record on your changes."),
    reset: bool = typer.Option(False, "--reset", help="Go back to the default."),
) -> None:
    """Show or set the author name recorded on changes in this project. It is
    saved in this project's config.toml; the default is your operating-system
    user."""
    from civex.identity import choose_name, local_actor

    config = cli_load_config()
    if reset or name:
        choose_name(config, None if reset else name)
    console.print(
        f"Recorded as {escape(local_actor(config.identity.name) or '(unknown)')}"
    )


@app.command("interval")
def interval(
    value: str = typer.Argument(help="Seconds between automatic syncs, or 'never'."),
) -> None:
    """Set how often the background sync runs. With 'never' it syncs only when
    you ask (`civex sync now`, or Sync now in the app)."""
    try:
        seconds = 0 if value.lower() == "never" else int(value)
    except ValueError:
        raise _fail(ValueError("Give a number of seconds, or 'never'"))
    c = _ctx()
    try:
        c.sync_svc.set_interval(seconds)
    except CivexError as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(
        "Sync only when asked." if seconds == 0 else f"Every {seconds} seconds."
    )


@app.command("files")
def files(
    mode: str = typer.Argument(
        None,
        help="'all' to keep a copy of every file, 'opened' to fetch only what is "
        "opened or exported. Leave out to see the setting.",
    ),
) -> None:
    """Choose which files this computer keeps a copy of. With 'all' (the
    default) files other devices add are downloaded in the background while
    civex is running; with 'opened' a file is downloaded only when it is opened
    or exported, for a computer short of space."""
    c = _ctx()
    try:
        if mode is not None:
            c.sync_svc.set_download_files(mode)
        s = c.sync_svc.status()
    except CivexError as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(
        "Keeps every file." if s.download_files == "all" else "Keeps files opened."
    )
    if s.files_to_fetch:
        console.print(
            f"{s.files_to_fetch} file(s) not downloaded yet "
            "(`civex sync fetch` downloads them now)."
        )


@app.command("fetch")
def fetch() -> None:
    """Download every file this project's records cite that isn't on this
    computer yet, now, with a progress bar. Stopping (Ctrl+C) keeps what has
    arrived; the rest comes later."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    c = _ctx()
    try:
        if not c.sync_svc.fetches_files:
            raise _fail(ValueError("This project doesn't follow an authority."))
        total = c.sync_svc.files_to_fetch()
        if not total:
            console.print("Every file is here.")
            return
        with Progress(
            TextColumn("Downloading files"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
            transient=True,
        ) as bar:
            task = bar.add_task("files", total=total)
            try:
                report = c.sync_svc.fetch_files(
                    progress=lambda done: bar.update(task, completed=done)
                )
            except KeyboardInterrupt:
                console.print("Stopped; what arrived is kept.")
                return
    except SyncError as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(f"[success]Downloaded {report.fetched} file(s).[/success]")
    if report.absent:
        console.print(
            f"[warning]{len(report.absent)} haven't reached the server yet: the "
            "device that added them hasn't sent them.[/warning]"
        )


@app.command("watch")
def watch() -> None:
    """Keep syncing in this terminal until stopped (Ctrl+C): after edits, on the
    interval, and backing off when the authority can't be reached."""
    import logging
    import threading

    from civex.context import build_local_context
    from civex.services.sync_worker import SyncWorker

    config = cli_load_config()
    if not config.sync.remote:
        console.print("[error]No authority is set. Use `civex sync connect`.[/error]")
        raise typer.Exit(1)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
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
    console.print(
        f"Files       keeps {'every file' if s.download_files == 'all' else 'files opened'}"
        + (f"; {s.files_to_fetch} not downloaded yet" if s.files_to_fetch else "")
    )
    console.print(f"Last synced {s.last_synced_at or 'never'}")
    if s.last_error:
        console.print(f"[warning]Last problem  {escape(s.last_error)}[/warning]")


@app.command("connect")
def connect(
    url: str = typer.Argument(
        help="The authority's address, e.g. https://civex.example.com"
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        envvar="CIVEX_SYNC_TOKEN",
        help="The device token the authority issued. Leave out to use the one "
        "this computer already holds for that address (connecting again after a "
        "copy stopped part way).",
    ),
) -> None:
    """Point this project at an authority. An empty project becomes a copy of
    it; a project with data fills an empty authority. Two projects that both
    hold data are refused."""
    c = _ctx()
    try:
        mode = _connect_showing_progress(c, url, token)
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
    record: str = typer.Option(
        None, "--record", help="Only those about this record (its id)."
    ),
) -> None:
    """List values that did not go in as made, with both sides."""
    entity = None
    if record:
        try:
            entity = uuid.UUID(record)
        except ValueError:
            raise _fail(ValueError("That is not a record id"))
    c = _ctx()
    try:
        found = c.sync_svc.conflicts(None if all_ else "open", entity_id=entity)
    finally:
        c.close()
    if not found:
        console.print("No conflicts.")
        return
    table = Table()
    for col in ("Id", "Kind", "What", "Field", "Yours", "Theirs", "State"):
        table.add_column(col)
    for f in found:
        table.add_row(
            str(f.id),
            f.kind,
            escape(f.record_name or f"{f.entity_type} {str(f.entity_id)[:8]}"),
            escape(f.field_label or f.field or (f.message or "")),
            escape(str(f.yours)),
            escape(str(f.theirs) + (f" ({f.theirs_actor})" if f.theirs_actor else "")),
            f.resolution or f.status,
        )
    console.print(table)


@app.command("resolve")
def resolve(
    conflict_id: str = typer.Argument(None, help="The conflict's id (not with --all)."),
    take: str = typer.Option(
        ...,
        "--take",
        help="'theirs' keeps what the authority has; 'mine' puts your value back as "
        "a new edit; 'value' puts the one given with --value; 'delete' deletes a "
        "record that was deleted there; 'retry' sends a refused change again from "
        "the record as it is now.",
    ),
    value: str = typer.Option(
        None,
        "--value",
        help="With --take value: the value to put in, as JSON (a number, true, a "
        'list, "quoted text"), or plain text.',
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Put your value back even though the record's value has changed again "
        "since the conflict was recorded.",
    ),
    all_: bool = typer.Option(
        False,
        "--all",
        help="Settle every open conflict that offers this way (narrow it with "
        "--kind), not one. Those that don't, or fail their checks, stay open.",
    ),
    kind: str = typer.Option(
        None,
        "--kind",
        help="With --all: only this kind (conflict, rejected or edit_vs_delete).",
    ),
) -> None:
    """Settle a conflict, or with --all every open one."""
    if all_ == (conflict_id is not None):
        raise _fail(ValueError("Give a conflict id, or --all"))
    if kind and not all_:
        raise _fail(ValueError("--kind goes with --all"))
    if (take == "value") != (value is not None):
        raise _fail(ValueError("--value goes with --take value, and it needs one"))
    if take == "value" and all_:
        raise _fail(ValueError("One value can't settle every conflict: give an id"))
    if all_:
        c = _ctx()
        try:
            report = c.sync_svc.resolve_many(take, kind=kind, force=force)
        except CivexError as e:
            raise _fail(e)
        finally:
            c.close()
        console.print(f"Settled {report.done}.")
        if report.not_offered:
            console.print(
                f"{report.not_offered} left open: they can't be settled with '{take}'."
            )
        for cid, message in report.failed:
            console.print(f"Left open {cid}: {escape(message)}")
        if report.failed:
            raise typer.Exit(1)
        return
    try:
        cid = uuid.UUID(conflict_id)
    except ValueError:
        raise _fail(ValueError("That is not a conflict id"))
    c = _ctx()
    try:
        c.sync_svc.resolve_conflict(cid, take, value=_read_value(value), force=force)
        if take == "retry":
            # Settled by the authority's answer, so ask for it now (as the app
            # does): it goes in, or it is refused again and says why.
            try:
                c.sync_svc.sync()
            except SyncError as e:
                console.print(f"Sent again; it goes with the next sync ({e}).")
                return
            left = [x for x in c.sync_svc.conflicts() if x.id == cid]
            console.print(
                f"Refused again: {escape(left[0].message or '')}"
                if left
                else "Sent again, and it went in."
            )
            return
    except CivexError as e:
        raise _fail(e)
    finally:
        c.close()
    console.print("Settled.")


@app.command("reopen")
def reopen(
    conflict_ids: list[str] = typer.Argument(
        ..., help="The ids of conflicts settled by keeping theirs."
    ),
) -> None:
    """Take back 'keep theirs': the conflicts are open again. (Putting your
    value back, deleting or sending again made an edit; undo that from history
    instead.)"""
    try:
        ids = [uuid.UUID(i) for i in conflict_ids]
    except ValueError:
        raise _fail(ValueError("That is not a conflict id"))
    c = _ctx()
    try:
        n = c.sync_svc.reopen_conflicts(ids)
    finally:
        c.close()
    console.print(f"Opened {n} again.")
    if n < len(ids):
        console.print(
            f"{len(ids) - n} not: only conflicts settled by keeping theirs can be."
        )


def _read_value(text: str | None) -> object:
    """A value given on the command line: JSON if it reads as JSON, else the
    text itself."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


@authority_app.command("enable")
def authority_enable() -> None:
    """Let devices with a token follow this project (serve it with `civex serve`)."""
    c = _ctx()
    try:
        c.sync_svc.set_serving(True)
    finally:
        c.close()
    console.print(
        "This project now accepts devices. Issue one a token with "
        "`civex sync device add <name>`."
    )


@authority_app.command("disable")
def authority_disable() -> None:
    """Stop accepting devices. Their tokens stay on record."""
    c = _ctx()
    try:
        c.sync_svc.set_serving(False)
    finally:
        c.close()
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
        _connect_showing_progress(c, url, token)
    except (SyncError, CivexError) as e:
        raise _fail(e)
    finally:
        c.close()
    console.print(f"[success]Cloned into {target}.[/success]")
