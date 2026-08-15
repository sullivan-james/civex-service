"""
civex clone <url> [local-dir] [--remote-civex <path>]

Clones a bare repository into a new local working directory.
Database rows are transferred via DTOs (SyncBundle). Objects are NOT downloaded
immediately — they are fetched on demand when accessed (lazy).

Use --remote-civex when civex is not on PATH on the remote (e.g. installed in a venv):
    civex clone ssh://js521/~/civex-test-repo --remote-civex ~/venv/bin/civex
"""

from __future__ import annotations

from pathlib import Path

import typer

from civex.console import console
from civex.sync.transport import SyncError, get_transport


def clone(
    url: str = typer.Argument(
        ..., help="Remote URL (ssh://user@host/path or file:///path)"
    ),
    local_dir: Path = typer.Argument(
        None, help="Destination directory (default: derived from URL)"
    ),
    remote_civex: str = typer.Option(
        "civex",
        "--remote-civex",
        help="Path to the civex executable on the remote (use when civex is in a venv, e.g. ~/venv/bin/civex)",
    ),
) -> None:
    """Clone a remote bare repository into a new local project."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from civex.db.migrate import ensure_schema_current
    from civex.sync.importer import apply_bundle

    try:
        transport, _remote_path = get_transport(url, remote_civex=remote_civex)
    except SyncError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    # Derive local directory name from the URL if not specified.
    if local_dir is None:
        last = url.rstrip("/").rsplit("/", 1)[-1]
        if last.endswith("_civex"):
            last = last[: -len("_civex")]
        local_dir = Path(last or "civex-repo")

    local_dir = local_dir.resolve()
    civex_dir = local_dir / "_civex"

    if civex_dir.exists():
        console.print(
            f"[error]Directory {local_dir} is already a civex project.[/error]"
        )
        raise typer.Exit(1)

    console.print(f"Cloning from [bold]{url}[/bold] into [bold]{local_dir}[/bold] ...")

    # Fetch the full bundle before creating any local state.
    try:
        bundle = transport.transfer_pack(since_seq=0)
    except SyncError as e:
        console.print(f"[error]Clone failed: {e}[/error]")
        raise typer.Exit(1)

    # Create local project structure.
    civex_dir.mkdir(parents=True)
    db_path = civex_dir / "civex.db"
    db_url = f"sqlite:///{db_path.as_posix()}"

    (civex_dir / "objects").mkdir()
    (civex_dir / "workflows").mkdir()
    (civex_dir / "plugins").mkdir()

    engine = create_engine(db_url)
    ensure_schema_current(engine)

    with Session(engine) as session:
        apply_bundle(session, bundle)
        session.commit()
    engine.dispose()

    remote_lines = f'[db]\nurl = "{db_url}"\n\n[remote]\nurl = "{url}"\n'
    if remote_civex != "civex":
        remote_lines += f'remote_civex = "{remote_civex}"\n'
    remote_lines += f"last_pulled_seq = {bundle.to_seq}\n"
    remote_lines += "last_pushed_seq = 0\n"
    (civex_dir / "config.toml").write_text(remote_lines)

    console.print("[success]Cloned successfully.[/success]")
    console.print(f"  Schemas    {len(bundle.schemas)}")
    console.print(f"  Datasets   {len(bundle.datasets)}")
    console.print(f"  Records    {len(bundle.records)}")
    console.print(
        f"  Objects    {len(bundle.object_refs)} available remotely (fetched on demand)"
    )
    console.print(f"  Local dir  {local_dir}")
