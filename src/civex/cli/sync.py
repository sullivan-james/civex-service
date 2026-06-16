"""
civex push  — push local changes to the remote bare repository.
civex pull  — pull remote changes into the local project.

Objects (binary blobs) are pushed before the DB bundle so the receiver can
access them immediately. On pull, object_refs are noted but not downloaded —
they are fetched lazily on next access.

Push blocks if the remote has commits the local hasn't pulled, preventing
silent overwrites (similar to git's fast-forward check).
"""
from __future__ import annotations

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
        transport, _path = get_transport(config.remote.url, remote_civex=config.remote.remote_civex)
    except SyncError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    # Divergence check: remote must not have commits beyond our last push.
    try:
        remote_seq = transport.get_head_seq()
    except SyncError as e:
        console.print(f"[error]Could not check remote state: {e}[/error]")
        raise typer.Exit(1)

    if remote_seq > config.remote.last_pushed_seq:
        console.print(
            "[error]Remote has commits you haven't pulled "
            f"(remote seq={remote_seq}, local last_pushed_seq={config.remote.last_pushed_seq}). "
            "Run `civex pull` first.[/error]"
        )
        raise typer.Exit(1)

    since_seq = config.remote.last_pushed_seq
    console.print(
        f"Pushing to [bold]{config.remote.url}[/bold]"
        + (f" (commits since seq {since_seq})" if since_seq else " (full)")
        + " ..."
    )

    from civex.repositories.local.audit_repo import LocalAuditRepository
    with Session(_engine()) as session:
        audit_repo = LocalAuditRepository(session)
        staged = audit_repo.count_staged()
        if staged["total"] > 0:
            audit_repo.create_commit(message="push")
            session.commit()
        bundle = export_bundle(session, since_seq)
        unpushed_ids = [c.id for c in audit_repo.list_unpushed_commits()]

    if bundle.to_seq == since_seq:
        console.print("[dim]Nothing to push — no new commits.[/dim]")
        return

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

    config.remote.last_pushed_seq = bundle.to_seq
    save_config(config)

    if unpushed_ids:
        with Session(_engine()) as session:
            LocalAuditRepository(session).mark_pushed(unpushed_ids)
            session.commit()

    console.print("[success]Push complete.[/success]")
    console.print(f"  Schemas    {len(bundle.schemas)}")
    console.print(f"  Datasets   {len(bundle.datasets)}")
    console.print(f"  Records    {len(bundle.records)}")
    console.print(f"  Deleted    {len(bundle.deleted_record_ids)}")
    console.print(f"  Objects    {pushed_objects} uploaded")
    console.print(f"  Seq        {since_seq} → {bundle.to_seq}")


def pull() -> None:
    """Pull remote changes into the local project."""
    config = cli_load_config()
    if config.remote is None:
        console.print("[error]No remote configured. Run `civex remote set <url>` first.[/error]")
        raise typer.Exit(1)

    try:
        transport, _path = get_transport(config.remote.url, remote_civex=config.remote.remote_civex)
    except SyncError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    since_seq = config.remote.last_pulled_seq
    console.print(
        f"Pulling from [bold]{config.remote.url}[/bold]"
        + (f" (commits since seq {since_seq})" if since_seq else " (full)")
        + " ..."
    )

    try:
        bundle = transport.transfer_pack(since_seq=since_seq)
    except SyncError as e:
        console.print(f"[error]Pull failed: {e}[/error]")
        raise typer.Exit(1)

    if bundle.to_seq == since_seq:
        console.print("[dim]Already up to date.[/dim]")
        return

    with Session(_engine()) as session:
        apply_bundle(session, bundle)
        session.commit()

    config.remote.last_pulled_seq = bundle.to_seq
    save_config(config)

    console.print("[success]Pull complete.[/success]")
    console.print(f"  Schemas    {len(bundle.schemas)}")
    console.print(f"  Datasets   {len(bundle.datasets)}")
    console.print(f"  Records    {len(bundle.records)}")
    console.print(f"  Deleted    {len(bundle.deleted_record_ids)}")
    console.print(f"  Objects    {len(bundle.object_refs)} available remotely (fetched on demand)")
    console.print(f"  Seq        {since_seq} → {bundle.to_seq}")
