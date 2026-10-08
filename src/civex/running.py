"""What is running from a copy of civex, so an update can stop it and start it
again.

On Windows a file in use can't be replaced, so a copy of civex can only be
updated while nothing runs from it: the desktop app, a `civex serve` in a
terminal. Each `civex serve` says it is running (`register`): a small record in
the per-user state folder, never in a project, holding what is needed to stop it
the way Ctrl+C would and to start it again as it was (its arguments, folder,
port, and a token only this user can read, which its `POST /api/server/stop`
asks for). An update stops those of its own copy (`others`, `stop`) and starts
them again afterwards, whatever the outcome (`start`).

A record whose process is gone is dropped when read, so a crash leaves nothing
behind for long.
"""

from __future__ import annotations

import atexit
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from civex.processes import pid_alive

STOP_HEADER = "X-Civex-Stop"
STOP_SECONDS = 20  # asked to stop politely, before being made to


def running_dir() -> Path:
    from civex.user_state import state_path

    return state_path().parent / "running"


def logs_dir() -> Path:
    """Where servers started again after an update write their output (off
    Windows, where they have no window): beside the update log."""
    from civex.user_state import state_path

    return state_path().parent


@dataclass
class Running:
    """One `civex serve`, as it said it was running."""

    pid: int
    prefix: str  # the copy it runs from (`sys.prefix`)
    argv: list[str]  # civex's own arguments: ["serve", "--port", "8100", ...]
    cwd: str
    host: str
    port: int
    token: str
    started: str

    def describe(self) -> str:
        return f"civex {' '.join(self.argv)} (in {self.cwd})"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Running:
        return cls(
            pid=int(data["pid"]),
            prefix=str(data["prefix"]),
            argv=[str(a) for a in data["argv"]],
            cwd=str(data["cwd"]),
            host=str(data.get("host") or "127.0.0.1"),
            port=int(data.get("port") or 8000),
            token=str(data.get("token") or ""),
            started=str(data.get("started") or ""),
        )


_mine: Running | None = None


def register(host: str, port: int) -> Running:
    """Say this `civex serve` is running, until it exits."""
    global _mine
    _mine = Running(
        pid=os.getpid(),
        prefix=sys.prefix,
        argv=[a for a in sys.argv[1:] if a != "--open"],
        cwd=os.getcwd(),
        host=host,
        port=port,
        token=secrets.token_urlsafe(24),
        started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    path = running_dir() / f"{os.getpid()}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_mine.to_dict()), "utf-8")
        if sys.platform != "win32":
            path.chmod(0o600)  # the token stops this server
    except OSError:
        return _mine  # only a convenience: an update then can't restart it
    atexit.register(_unregister, path)
    return _mine


def _unregister(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def accepts_stop(token: str | None) -> bool:
    """Whether a stop request carries this server's own token."""
    return bool(_mine and token and hmac.compare_digest(_mine.token, token))


def _same_copy(prefix: str) -> bool:
    try:
        return Path(prefix).resolve() == Path(sys.prefix).resolve()
    except OSError:
        return False


def others(prefix: str | None = None) -> list[Running]:
    """Every other `civex serve` running from this copy (or `prefix`'s)."""
    found: list[Running] = []
    folder = running_dir()
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.json")):
        try:
            record = Running.from_dict(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not pid_alive(record.pid):
            _unregister(path)
            continue
        if record.pid == os.getpid():
            continue
        same = (
            _same_copy(record.prefix)
            if prefix is None
            else Path(record.prefix).resolve() == Path(prefix).resolve()
        )
        if same:
            found.append(record)
    return found


def _ask_to_stop(record: Running) -> bool:
    host = record.host
    if host in ("", "0.0.0.0", "::", "[::]"):
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    request = urllib.request.Request(
        f"http://{host}:{record.port}/api/server/stop",
        data=b"{}",
        method="POST",
        headers={STOP_HEADER: record.token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:
            return 200 <= answer.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _force(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    import signal

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except OSError:
            return
        deadline = time.monotonic() + 5
        while pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if not pid_alive(pid):
            return


def stop(record: Running, seconds: float = STOP_SECONDS) -> bool:
    """Stop a server the way Ctrl+C does (it finishes what it is doing and
    closes), and make it stop if it doesn't in time. True once it is gone."""
    if _ask_to_stop(record):
        deadline = time.monotonic() + seconds
        while pid_alive(record.pid) and time.monotonic() < deadline:
            time.sleep(0.2)
    if pid_alive(record.pid):
        _force(record.pid)
    gone = not pid_alive(record.pid)
    if gone:
        _unregister(running_dir() / f"{record.pid}.json")
    return gone


def start_command(record: Running) -> list[str]:
    """How to start a stopped server again: its own copy's Python, running
    civex with the arguments it had."""
    prefix = Path(record.prefix)
    if sys.platform == "win32":
        python = prefix / "Scripts" / "python.exe"
    else:
        python = prefix / "bin" / "python"
    return [str(python), "-m", "civex.main", *record.argv]


def start(record: Running) -> None:
    """Start a server again as it was, in a window of its own on Windows (a
    server people can see and close), else with its output in a log."""
    kwargs: dict[str, Any] = {
        "cwd": record.cwd,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
    else:
        folder = logs_dir()
        folder.mkdir(parents=True, exist_ok=True)
        log = open(folder / f"serve-{record.port}.log", "a", encoding="utf-8")  # noqa: SIM115
        kwargs.update(start_new_session=True, stdout=log, stderr=subprocess.STDOUT)
    subprocess.Popen(start_command(record), **kwargs)


def pending_file() -> Path:
    """Servers the desktop app stopped to update, for it to start again when it
    opens (the launcher that updates it can't: it is older than this)."""
    from civex.updates import app_home

    return app_home() / "restart-after-update.json"


def remember(records: list[Running]) -> None:
    pending_file().parent.mkdir(parents=True, exist_ok=True)
    pending_file().write_text(json.dumps([r.to_dict() for r in records]), "utf-8")


def start_remembered() -> list[Running]:
    """Start the servers stopped for an update (the app does this as it opens,
    whether or not the update worked). What it started."""
    path = pending_file()
    try:
        records = [Running.from_dict(d) for d in json.loads(path.read_text("utf-8"))]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    path.unlink(missing_ok=True)
    started = []
    for record in records:
        try:
            start(record)
            started.append(record)
        except OSError:
            continue
    return started
