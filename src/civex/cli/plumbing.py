"""
Plumbing commands — internal, called by SSHTransport on the remote side.

These mirror git's upload-pack / receive-pack model: the SSH client spawns these
commands on the remote machine and communicates over stdin/stdout.

  civex transfer-pack <bare-path> [--since-seq N]
  civex receive-pack  <bare-path>
  civex head-seq      <bare-path>
  civex get-object    <bare-path> <sha256>
  civex put-object    <bare-path> <sha256>
"""
from __future__ import annotations

import sys
from pathlib import Path

import typer

from civex.sync.bundle import SyncBundle
from civex.sync.exporter import export_bundle
from civex.sync.importer import apply_bundle

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session


def transfer_pack(
    bare_path: Path = typer.Argument(..., help="Path to the bare repository directory"),
    since_seq: int = typer.Option(0, "--since-seq", help="Export only commits with seq > this value"),
) -> None:
    """[Plumbing] Export repository data to stdout as JSON (called by SSH client)."""
    bare_path = bare_path.resolve()
    _require_bare(bare_path)

    engine = create_engine(f"sqlite:///{bare_path / 'civex.db'}")
    with Session(engine) as session:
        bundle = export_bundle(session, since_seq)
    engine.dispose()

    sys.stdout.buffer.write(bundle.to_json().encode())
    sys.stdout.buffer.flush()


def receive_pack(
    bare_path: Path = typer.Argument(..., help="Path to the bare repository directory"),
) -> None:
    """[Plumbing] Apply a JSON bundle from stdin to the bare repository (called by SSH client)."""
    bare_path = bare_path.resolve()
    _require_bare(bare_path)

    raw = sys.stdin.buffer.read()
    bundle = SyncBundle.from_json(raw.decode())

    engine = create_engine(f"sqlite:///{bare_path / 'civex.db'}")
    with Session(engine) as session:
        apply_bundle(session, bundle)
        session.commit()
    engine.dispose()


def head_seq(
    bare_path: Path = typer.Argument(..., help="Path to the bare repository directory"),
) -> None:
    """[Plumbing] Print the maximum commit sequence number to stdout (called by SSH client)."""
    bare_path = bare_path.resolve()
    _require_bare(bare_path)

    from civex.db.models import Commit
    engine = create_engine(f"sqlite:///{bare_path / 'civex.db'}")
    with Session(engine) as session:
        seq = session.query(func.max(Commit.seq)).scalar() or 0
    engine.dispose()

    sys.stdout.write(str(seq) + "\n")
    sys.stdout.flush()


def get_object(
    bare_path: Path = typer.Argument(..., help="Path to the bare repository directory"),
    sha256: str = typer.Argument(..., help="SHA-256 hex digest of the object"),
) -> None:
    """[Plumbing] Write a stored object's bytes to stdout (called by SSH client)."""
    bare_path = bare_path.resolve()
    _require_bare(bare_path)

    obj_path = bare_path / "objects" / sha256[:2] / sha256[2:]
    if not obj_path.exists():
        typer.echo(f"Object {sha256} not found", err=True)
        raise typer.Exit(1)

    sys.stdout.buffer.write(obj_path.read_bytes())
    sys.stdout.buffer.flush()


def put_object(
    bare_path: Path = typer.Argument(..., help="Path to the bare repository directory"),
    sha256: str = typer.Argument(..., help="SHA-256 hex digest of the object"),
) -> None:
    """[Plumbing] Read bytes from stdin and store as an object (called by SSH client)."""
    bare_path = bare_path.resolve()
    _require_bare(bare_path)

    data = sys.stdin.buffer.read()
    obj_path = bare_path / "objects" / sha256[:2] / sha256[2:]
    if not obj_path.exists():
        obj_path.parent.mkdir(parents=True, exist_ok=True)
        obj_path.write_bytes(data)


def _require_bare(path: Path) -> None:
    if not (path / "CIVEX_BARE").exists():
        typer.echo(f"{path} is not a bare civex repository (missing CIVEX_BARE marker)", err=True)
        raise typer.Exit(1)
