"""`civex sync ssh-serve`: the far end of an `ssh://` address.

A device reaches an authority over SSH the way git does: it runs `ssh host
civex sync ssh-serve <project> --socket <path>` (`services/ssh_tunnel.py`),
and nothing runs on that machine between syncs. This serves the very app
`civex serve --sync-only` runs, on a Unix socket only this user can open, and
SSH forwards the device's local port to it: every request is ordinary HTTP to
the ordinary server, so signing in, protocol checks, files and everything the
authority decides are the same as over HTTPS. Nothing here speaks the protocol.

It stops when the device hangs up (stdin closes) or no connection has been
open for `IDLE_SECONDS`, and holds the project for this machine meanwhile
(`civex/project_host.py`).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

# Written to stdout once the socket is listening: the device waits for it
# (anything a login shell prints first is skipped).
READY = "civex-ssh-ready"
IDLE_SECONDS = 300.0
# Exit status for a refusal that waiting can fix (EX_TEMPFAIL): the project is
# open on another machine. Any other failure exits 1.
TRY_LATER = 75


def serve_over_ssh(project: str, socket_path: str, idle: float = IDLE_SECONDS) -> int:
    import uvicorn

    from civex.config import read_sync_flag
    from civex.project_host import HostLock, OpenElsewhere

    root = Path(project).expanduser()
    if not (root / "_civex").is_dir():
        return _refuse(f"{project} is not a civex project on this machine.")
    if not read_sync_flag(root / "_civex", "serve"):
        return _refuse(
            f"The project at {project} is not an authority: run `civex sync "
            "authority enable` there first."
        )
    os.chdir(root)
    lock = HostLock(root / "_civex")
    try:
        lock.acquire()
    except OpenElsewhere as e:
        return _refuse(str(e), TRY_LATER)
    except OSError as e:
        return _refuse(f"Could not mark the project as open here: {e}")

    sock = Path(socket_path)
    # Only this user may reach the socket: its folder is made private first.
    sock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(sock.parent, 0o700)
    from civex.server.app import create_sync_app

    server = uvicorn.Server(
        uvicorn.Config(create_sync_app(), uds=str(sock), log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            if not thread.is_alive():
                return _refuse("The sync server could not start here.")
            time.sleep(0.02)
        print(READY, flush=True)
        _watch(server, idle)
        server.should_exit = True
        thread.join(timeout=10)
    finally:
        lock.release()
        sock.unlink(missing_ok=True)
        try:
            sock.parent.rmdir()
        except OSError:
            pass
    return 0


def _watch(server, idle: float) -> None:  # noqa: ANN001 — uvicorn.Server
    """Until the device hangs up or nothing has been connected for `idle`."""
    gone = threading.Event()

    def hang_up() -> None:
        while sys.stdin.buffer.read(4096):
            pass
        gone.set()

    threading.Thread(target=hang_up, daemon=True).start()
    quiet_since = time.monotonic()
    while not gone.wait(1.0):
        if server.server_state.connections:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since > idle:
            return


def _refuse(message: str, code: int = 1) -> int:
    print(message, file=sys.stderr, flush=True)
    return code


__all__ = ["IDLE_SECONDS", "READY", "TRY_LATER", "serve_over_ssh"]
