"""
Transport layer for remote sync.

Two implementations:
  LocalTransport  — file:// or absolute path; opens the bare repo's SQLite directly.
  SSHTransport    — ssh://user@host/path; spawns civex plumbing commands on the remote.

Usage:
  transport = get_transport("ssh://user@host:/srv/repos/myrepo")
  bundle = transport.transfer_pack(since=None)   # full clone
  transport.receive_pack(bundle)                 # push bundle to remote
  data = transport.get_object("sha256hex")       # lazy object fetch
  transport.put_object("sha256hex", data)        # push object
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civex.db.models import Base
from civex.sync.bundle import SyncBundle
from civex.sync.exporter import export_bundle
from civex.sync.importer import apply_bundle


class SyncError(RuntimeError):
    pass


class LocalTransport:
    """Accesses a bare repo on the local filesystem via SQLAlchemy."""

    def __init__(self, bare_path: Path) -> None:
        self._path = bare_path.resolve()

    def transfer_pack(self, since: datetime | None) -> SyncBundle:
        engine = create_engine(f"sqlite:///{self._path / 'civex.db'}")
        with Session(engine) as session:
            bundle = export_bundle(session, since)
        engine.dispose()
        return bundle

    def receive_pack(self, bundle: SyncBundle) -> None:
        engine = create_engine(f"sqlite:///{self._path / 'civex.db'}")
        with Session(engine) as session:
            apply_bundle(session, bundle)
            session.commit()
        engine.dispose()

    def get_object(self, sha256: str) -> bytes:
        obj_path = self._path / "objects" / sha256[:2] / sha256[2:]
        if not obj_path.exists():
            raise SyncError(f"Object {sha256} not found in remote")
        return obj_path.read_bytes()

    def put_object(self, sha256: str, data: bytes) -> None:
        obj_path = self._path / "objects" / sha256[:2] / sha256[2:]
        if not obj_path.exists():
            obj_path.parent.mkdir(parents=True, exist_ok=True)
            obj_path.write_bytes(data)


class SSHTransport:
    """Accesses a bare repo on a remote host via SSH + civex plumbing commands."""

    def __init__(self, host: str, remote_path: str, user: str | None = None, port: int | None = None) -> None:
        self._host = host
        self._user = user
        self._port = port
        self._remote_path = remote_path

    def _ssh(self, *remote_args: str, stdin: bytes | None = None) -> bytes:
        dest = f"{self._user}@{self._host}" if self._user else self._host
        cmd = ["ssh"]
        if self._port:
            cmd += ["-p", str(self._port)]
        cmd += [dest] + list(remote_args)
        result = subprocess.run(cmd, input=stdin, capture_output=True)
        if result.returncode != 0:
            raise SyncError(f"SSH command failed: {result.stderr.decode().strip()}")
        return result.stdout

    def transfer_pack(self, since: datetime | None) -> SyncBundle:
        args = ["civex", "transfer-pack", self._remote_path]
        if since is not None:
            args += ["--since", since.isoformat()]
        raw = self._ssh(*args)
        return SyncBundle.from_json(raw.decode())

    def receive_pack(self, bundle: SyncBundle) -> None:
        self._ssh("civex", "receive-pack", self._remote_path, stdin=bundle.to_json().encode())

    def get_object(self, sha256: str) -> bytes:
        return self._ssh("civex", "get-object", self._remote_path, sha256)

    def put_object(self, sha256: str, data: bytes) -> None:
        self._ssh("civex", "put-object", self._remote_path, sha256, stdin=data)


def get_transport(url: str) -> tuple[LocalTransport | SSHTransport, str]:
    """
    Parse a remote URL and return (transport, remote_path).

    Supported schemes:
      ssh://[user@]host[:port]/path
      file:///path
      /abs/path  (treated as file://)
    """
    if url.startswith("/") or url.startswith("./"):
        return LocalTransport(Path(url)), url

    parsed = urlparse(url)

    if parsed.scheme == "file":
        return LocalTransport(Path(parsed.path)), parsed.path

    if parsed.scheme == "ssh":
        netloc = parsed.netloc  # "user@host" or "host" or "user@host:port"
        path = parsed.path      # "/path/to/repo" or "/~/home-relative"
        user: str | None = None
        host: str = netloc
        port: int | None = None

        if "@" in netloc:
            user, host = netloc.rsplit("@", 1)

        # urllib may parse port from netloc if present as "host:port"
        if parsed.port:
            port = parsed.port
            # Remove ":port" from host string
            host = host.rsplit(":", 1)[0]

        # URL parsing always prepends "/" to the path component, turning
        # ssh://host/~/repo into path="/~/repo". Strip the leading "/" when
        # the path is home-relative so the remote shell expands "~" correctly.
        if path.startswith("/~"):
            path = path[1:]

        return SSHTransport(host=host, remote_path=path, user=user, port=port), path

    raise SyncError(f"Unsupported remote URL scheme '{parsed.scheme}'. Use ssh:// or file://")
