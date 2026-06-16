"""
Transport layer for remote sync.

Three implementations:
  LocalTransport  — file:// or absolute path; opens the bare repo's SQLite directly.
  SSHTransport    — ssh://user@host/path; spawns civex plumbing commands on the remote.
  HttpTransport   — https://hub/owner/repo; talks to a civex-hub server via HTTP(S).

Usage:
  transport = get_transport("https://civexhub.example.com/alice/myrepo")
  bundle = transport.transfer_pack(since_seq=0)    # full clone
  transport.receive_pack(bundle)                   # push bundle to remote
  remote_seq = transport.get_head_seq()            # highest commit seq on remote
  data = transport.get_object("sha256hex")         # lazy object fetch
  transport.put_object("sha256hex", data)          # push object
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

from civex.db.models import Base, Commit
from civex.sync.bundle import SyncBundle
from civex.sync.exporter import export_bundle
from civex.sync.importer import apply_bundle


class SyncError(RuntimeError):
    pass


class LocalTransport:
    """Accesses a bare repo on the local filesystem via SQLAlchemy."""

    def __init__(self, bare_path: Path) -> None:
        self._path = bare_path.resolve()

    def transfer_pack(self, since_seq: int = 0) -> SyncBundle:
        engine = create_engine(f"sqlite:///{self._path / 'civex.db'}")
        with Session(engine) as session:
            bundle = export_bundle(session, since_seq)
        engine.dispose()
        return bundle

    def receive_pack(self, bundle: SyncBundle) -> None:
        engine = create_engine(f"sqlite:///{self._path / 'civex.db'}")
        with Session(engine) as session:
            apply_bundle(session, bundle)
            session.commit()
        engine.dispose()

    def get_head_seq(self) -> int:
        engine = create_engine(f"sqlite:///{self._path / 'civex.db'}")
        with Session(engine) as session:
            seq = session.query(func.max(Commit.seq)).scalar() or 0
        engine.dispose()
        return seq

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

    def __init__(
        self,
        host: str,
        remote_path: str,
        user: str | None = None,
        port: int | None = None,
        civex_cmd: str = "civex",
    ) -> None:
        self._host = host
        self._user = user
        self._port = port
        self._remote_path = remote_path
        self._civex = civex_cmd

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

    def transfer_pack(self, since_seq: int = 0) -> SyncBundle:
        raw = self._ssh(self._civex, "transfer-pack", self._remote_path, "--since-seq", str(since_seq))
        return SyncBundle.from_json(raw.decode())

    def receive_pack(self, bundle: SyncBundle) -> None:
        self._ssh(self._civex, "receive-pack", self._remote_path, stdin=bundle.to_json().encode())

    def get_head_seq(self) -> int:
        raw = self._ssh(self._civex, "head-seq", self._remote_path)
        return int(raw.decode().strip())

    def get_object(self, sha256: str) -> bytes:
        return self._ssh(self._civex, "get-object", self._remote_path, sha256)

    def put_object(self, sha256: str, data: bytes) -> None:
        self._ssh(self._civex, "put-object", self._remote_path, sha256, stdin=data)


class HttpTransport:
    """Accesses a civex-hub repo over HTTP(S)."""

    def __init__(self, base_url: str, owner: str, repo: str, token: str) -> None:
        self._base = base_url.rstrip("/")
        self._owner = owner
        self._repo = repo
        self._token = token

    def _url(self, path: str) -> str:
        return f"{self._base}/api/v1/repos/{self._owner}/{self._repo}/{path}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _request(self, method: str, url: str, data: bytes | None = None) -> bytes:
        import urllib.request
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise SyncError(f"HTTP {e.code} from {url}: {e.read().decode(errors='replace')}")

    def transfer_pack(self, since_seq: int = 0) -> SyncBundle:
        raw = self._request("GET", self._url(f"transfer-pack?since_seq={since_seq}"))
        return SyncBundle.from_json(raw.decode())

    def receive_pack(self, bundle: SyncBundle) -> None:
        self._request("POST", self._url("receive-pack"), data=bundle.to_json().encode())

    def get_head_seq(self) -> int:
        raw = self._request("GET", self._url("head-seq"))
        return int(raw.decode().strip())

    def get_object(self, sha256: str) -> bytes:
        return self._request("GET", self._url(f"objects/{sha256}"))

    def put_object(self, sha256: str, data: bytes) -> None:
        self._request("PUT", self._url(f"objects/{sha256}"), data=data)


def _load_token(base_url: str) -> str:
    """Read the stored auth token for a hub URL from ~/.civex/tokens.toml."""
    tokens_path = Path.home() / ".civex" / "tokens.toml"
    if not tokens_path.exists():
        raise SyncError(
            f"Not logged in to {base_url}. Run `civex auth login {base_url}` first."
        )
    try:
        import tomllib
        with open(tokens_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise SyncError(f"Failed to read token store: {e}")

    entry = data.get(base_url, {})
    token = entry.get("token")
    if not token:
        raise SyncError(
            f"No token found for {base_url}. Run `civex auth login {base_url}` first."
        )
    return token


def get_transport(url: str, remote_civex: str = "civex") -> tuple[LocalTransport | SSHTransport | HttpTransport, str]:
    """
    Parse a remote URL and return (transport, remote_path).

    Supported schemes:
      https://civexhub.example.com/owner/repo  (civex-hub)
      http://localhost:8001/owner/repo          (civex-hub, local dev)
      ssh://[user@]host[:port]/path
      file:///path
      /abs/path  (treated as file://)
    """
    if url.startswith("/") or url.startswith("./"):
        return LocalTransport(Path(url)), url

    parsed = urlparse(url)

    if parsed.scheme == "file":
        return LocalTransport(Path(parsed.path)), parsed.path

    if parsed.scheme in ("http", "https"):
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2:
            raise SyncError(
                f"Invalid civex-hub URL '{url}'. Expected https://hub/owner/repo"
            )
        owner, repo_name = parts[0], parts[1]
        token = _load_token(base_url)
        return HttpTransport(base_url, owner, repo_name, token), parsed.path

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

        return SSHTransport(host=host, remote_path=path, user=user, port=port, civex_cmd=remote_civex), path

    raise SyncError(f"Unsupported remote URL scheme '{parsed.scheme}'. Use https://, ssh://, or file://")
