"""
civex clone <url> [local-dir]

Clones a bare repository into a new local working directory.
Database rows are transferred via DTOs (SyncBundle). Objects are NOT downloaded
immediately — they are fetched on demand when accessed (lazy).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civex.console import console
from civex.db.models import Base
from civex.sync.importer import apply_bundle
from civex.sync.transport import SyncError, get_transport


def clone(
    url: str = typer.Argument(..., help="Remote URL (ssh://user@host:/path or file:///path)"),
    local_dir: Path = typer.Argument(None, help="Destination directory (default: derived from URL)"),
) -> None:
    """Clone a remote bare repository into a new local project."""
    try:
        transport, _remote_path = get_transport(url)
    except SyncError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    # Derive local directory name from the URL if not specified.
    if local_dir is None:
        last = url.rstrip("/").rsplit("/", 1)[-1]
        if last.endswith(".civex"):
            last = last[: -len(".civex")]
        local_dir = Path(last or "civex-repo")

    local_dir = local_dir.resolve()
    civex_dir = local_dir / ".civex"

    if civex_dir.exists():
        console.print(f"[error]Directory {local_dir} is already a civex project.[/error]")
        raise typer.Exit(1)

    console.print(f"Cloning from [bold]{url}[/bold] into [bold]{local_dir}[/bold] ...")

    # Fetch the full bundle before creating any local state.
    try:
        bundle = transport.transfer_pack(since=None)
    except SyncError as e:
        console.print(f"[error]Clone failed: {e}[/error]")
        raise typer.Exit(1)

    # Create local project structure.
    civex_dir.mkdir(parents=True)
    db_path = civex_dir / "civex.db"
    db_url = f"sqlite:///{db_path}"

    (civex_dir / "objects").mkdir()
    (civex_dir / "workflows").mkdir()
    (civex_dir / "plugins").mkdir()

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        apply_bundle(session, bundle)
        session.commit()
    engine.dispose()

    now = datetime.now(timezone.utc)
    (civex_dir / "config.toml").write_text(
        f'[db]\nurl = "{db_url}"\n'
        f'\n[remote]\nurl = "{url}"\n'
        f'last_pulled_at = "{now.isoformat()}"\n'
    )

    n_schemas = len(bundle.schemas)
    n_datasets = len(bundle.datasets)
    n_records = len(bundle.records)
    n_objects = len(bundle.object_refs)

    console.print(f"[success]Cloned successfully.[/success]")
    console.print(f"  Schemas    {n_schemas}")
    console.print(f"  Datasets   {n_datasets}")
    console.print(f"  Records    {n_records}")
    console.print(f"  Objects    {n_objects} available remotely (fetched on demand)")
    console.print(f"  Local dir  {local_dir}")
