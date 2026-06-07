"""
civex push  — push local changes to the remote bare repository.
civex pull  — pull remote changes into the local project.

Objects (binary blobs) are pushed before the DB bundle so the receiver can
access them immediately. On pull, object_refs are noted but not downloaded —
they are fetched lazily on next access.
"""
from __future__ import annotations

from datetime import datetime, timezone

import typer

from civex.cli.utils import cli_load_config
from civex.config import save_config
from civex.console import console
from civex.db.session import _engine
from civex.sync.exporter import export_bundle
from civex.sync.importer import apply_bundle
from civex.sync.transport import SyncError, get_transport

from sqlalchemy.orm import Session


def push() -> None:
    """Push local changes to the remote bare repository."""
    config = cli_load_config()
    if config.remote is None:
        console.print("[error]No remote configured. Run `civex remote set <url>` first.[/error]")
        raise typer.Exit(1)

    try:
        transport, _path = get_transport(config.remote.url)
    except SyncError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    since = config.remote.last_pushed_at
    console.print(f"Pushing to [bold]{config.remote.url}[/bold]" + (f" (changes since {since.date()})" if since else " (full)") + " ...")

    with Session(_engine()) as session:
        bundle = export_bundle(session, since)

    # Push objects referenced by the bundle before the DB rows.
    from civex.repositories.local.file_store import LocalFileObjectStore
    local_store = LocalFileObjectStore(config.objects_dir)
    pushed_objects = 0
    for sha256 in bundle.object_refs:
        if local_store.exists(sha256):
            try:
                transport.put_object(sha256, local_store.get(sha256))
                pushed_objects += 1
            except SyncError as e:
                console.print(f"[warning]Could not push object {sha256[:12]}…: {e}[/warning]")

    try:
        transport.receive_pack(bundle)
    except SyncError as e:
        console.print(f"[error]Push failed: {e}[/error]")
        raise typer.Exit(1)

    now = datetime.now(timezone.utc)
    config.remote.last_pushed_at = now
    save_config(config)

    console.print(f"[success]Push complete.[/success]")
    console.print(f"  Schemas    {len(bundle.schemas)}")
    console.print(f"  Datasets   {len(bundle.datasets)}")
    console.print(f"  Records    {len(bundle.records)}")
    console.print(f"  Objects    {pushed_objects} uploaded")


def pull() -> None:
    """Pull remote changes into the local project."""
    config = cli_load_config()
    if config.remote is None:
        console.print("[error]No remote configured. Run `civex remote set <url>` first.[/error]")
        raise typer.Exit(1)

    try:
        transport, _path = get_transport(config.remote.url)
    except SyncError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    since = config.remote.last_pulled_at
    console.print(f"Pulling from [bold]{config.remote.url}[/bold]" + (f" (changes since {since.date()})" if since else " (full)") + " ...")

    try:
        bundle = transport.transfer_pack(since=since)
    except SyncError as e:
        console.print(f"[error]Pull failed: {e}[/error]")
        raise typer.Exit(1)

    with Session(_engine()) as session:
        apply_bundle(session, bundle)
        session.commit()

    now = datetime.now(timezone.utc)
    config.remote.last_pulled_at = now
    save_config(config)

    console.print(f"[success]Pull complete.[/success]")
    console.print(f"  Schemas    {len(bundle.schemas)}")
    console.print(f"  Datasets   {len(bundle.datasets)}")
    console.print(f"  Records    {len(bundle.records)}")
    console.print(f"  Objects    {len(bundle.object_refs)} available remotely (fetched on demand)")
