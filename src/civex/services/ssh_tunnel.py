"""Reaching an authority at an `ssh://` address.

`ssh://[user@]host[:port]/path/to/project` (`/~/...` for a path in the home
folder; `?civex=<command>` when civex isn't on the remote's PATH or in
`~/.local/bin`). Like git, nothing needs to run there between syncs: the
device starts `civex sync ssh-serve` over SSH (`server/ssh_end.py`), which
serves the sync API on a private Unix socket, and SSH forwards a port on this
machine to it. Everything else is the ordinary HTTP transport talking to
`http://127.0.0.1:<port>`: this module only opens the way.

SSH runs with `BatchMode`, since a background sync can't type a password:
signing in needs a key (an agent is fine) or an open `ControlMaster`
connection. `CIVEX_SSH_COMMAND` replaces `ssh` (as `GIT_SSH_COMMAND` does).
One tunnel per address stays open and is reused; the far end stops by itself
once nothing has been connected for a few minutes, and the next call opens a
new one.
"""

from __future__ import annotations

import atexit
import os
import shlex
import socket
import subprocess
import threading
import time
import urllib.parse
import uuid
from collections import deque
from dataclasses import dataclass

from civex.domain.sync import SyncError

SCHEME = "ssh"
_READY = (
    "civex-ssh-ready"  # server/ssh_end.READY (not imported: that pulls in the server)
)
_TRY_LATER = 75  # server/ssh_end.TRY_LATER
_START_SECONDS = 60.0
_FRAME = " │╭╮╰╯─┃━┏┓┗┛"


@dataclass(frozen=True)
class SshAddress:
    host: str  # with `user@` when given
    port: int | None
    path: str
    civex: str | None  # the command that runs civex there

    @classmethod
    def parse(cls, url: str) -> SshAddress:
        parts = urllib.parse.urlsplit(url)
        path = urllib.parse.unquote(parts.path)
        if parts.scheme != SCHEME or not parts.hostname or path in ("", "/"):
            raise SyncError(
                "An SSH address is ssh://[user@]host/path/to/project",
                retryable=False,
            )
        if path.startswith("/~"):
            path = path[1:]
        host = (
            f"{parts.username}@{parts.hostname}" if parts.username else parts.hostname
        )
        civex = urllib.parse.parse_qs(parts.query).get("civex", [None])[0]
        return cls(host=host, port=parts.port, path=path, civex=civex)

    def command(self, local_port: int, remote_socket: str) -> list[str]:
        ssh = shlex.split(os.environ.get("CIVEX_SSH_COMMAND") or "ssh")
        port = ["-p", str(self.port)] if self.port else []
        civex = self.civex or 'PATH="$PATH:$HOME/.local/bin" exec civex'
        remote = (
            f"{civex} sync ssh-serve {shlex.quote(self.path)} "
            f"--socket {shlex.quote(remote_socket)}"
        )
        return [
            *ssh,
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            *port,
            "-L",
            f"127.0.0.1:{local_port}:{remote_socket}",
            self.host,
            # Through `sh`, whatever the login shell (csh and fish read
            # `VAR=value cmd` differently).
            f"sh -c {shlex.quote(remote)}",
        ]


def is_ssh(url: str) -> bool:
    return url.lower().startswith(f"{SCHEME}://")


class _Tunnel:
    def __init__(self, address: SshAddress) -> None:
        self.port = _free_port()
        remote_socket = f"/tmp/civex-{uuid.uuid4().hex[:16]}/sync.sock"
        self._proc = subprocess.Popen(
            address.command(self.port, remote_socket),
            stdin=subprocess.PIPE,  # closing it is how the far end hears we left
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        self._said: deque[str] = deque(maxlen=20)
        self._ready = threading.Event()
        threading.Thread(
            target=self._read, args=(self._proc.stdout,), daemon=True
        ).start()
        threading.Thread(
            target=self._read, args=(self._proc.stderr,), daemon=True
        ).start()
        self._host = address.host
        self._wait_until_ready()

    def _read(self, stream) -> None:  # noqa: ANN001
        """Keeps both pipes drained (a full pipe would stall the far end) and
        the last lines for an error message."""
        for line in stream:
            line = line.rstrip()
            if line == _READY:
                self._ready.set()
            elif line:
                self._said.append(line)

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + _START_SECONDS
        while not self._ready.wait(0.05):
            if self._proc.poll() is not None:
                time.sleep(0.1)  # let the readers catch its last words
                raise self._failure()
            if time.monotonic() > deadline:
                self.close()
                raise SyncError(f"{self._host} took too long to answer over SSH")
        # ssh listens on the local port before running the command, so it is
        # open by now; this only waits out a slow start.
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                return
            except OSError:
                if self._proc.poll() is not None:
                    raise self._failure()
                time.sleep(0.05)

    def _failure(self) -> SyncError:
        # The far end's words without the frame a CLI error is drawn in.
        lines = [s for line in self._said if (s := line.strip(_FRAME))]
        said = " ".join(lines)
        code = self._proc.returncode
        last = said or f"ssh exited with {code}"
        if code == _TRY_LATER:
            return SyncError(last)
        if "No such command" in said:
            return SyncError(
                f"The civex on {self._host} is too old to be reached by ssh:// "
                "(it has no `civex sync ssh-serve`): update it there, or add "
                "?civex=/path/to/a/newer/civex to the address.",
                retryable=False,
            )
        if "Permission denied" in said:
            return SyncError(
                f"SSH could not sign in to {self._host}: civex can't type a "
                "password, so it needs an SSH key (an agent is fine) or an open "
                "ControlMaster connection.",
                retryable=False,
            )
        if "Host key verification failed" in said:
            return SyncError(
                f"{self._host} isn't a known SSH host yet: connect once with "
                f"`ssh {self._host}` in a terminal to accept its key.",
                retryable=False,
            )
        if code == 127 or "command not found" in said:
            return SyncError(
                f"civex isn't installed on {self._host} (or isn't on its PATH): "
                "install it there, or add ?civex=/path/to/civex to the address.",
                retryable=False,
            )
        if code == 255:  # ssh's own failure: the network, most likely
            return SyncError(f"Could not reach {self._host} over SSH: {last}")
        return SyncError(f"{self._host}: {last}", retryable=False)

    def alive(self) -> bool:
        return self._proc.poll() is None

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_tunnels: dict[str, _Tunnel] = {}
_lock = threading.Lock()


def local_url(url: str) -> str:
    """The `http://127.0.0.1:<port>` an `ssh://` address is reached at,
    opening the tunnel when there is none (or the last one has closed)."""
    address = SshAddress.parse(url)
    with _lock:
        tunnel = _tunnels.get(url)
        if tunnel is None or not tunnel.alive():
            tunnel = _tunnels[url] = _Tunnel(address)
        return f"http://127.0.0.1:{tunnel.port}"


@atexit.register
def close_all() -> None:
    with _lock:
        for tunnel in _tunnels.values():
            tunnel.close()
        _tunnels.clear()


__all__ = ["SshAddress", "close_all", "is_ssh", "local_url"]
