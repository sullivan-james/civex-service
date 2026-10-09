"""Which machine has a project open for sync over SSH.

University and lab home folders are usually one network drive mounted on every
machine. A device that reaches `ssh://lab-03/~/birds` one day and
`ssh://lab-07/~/birds` the next would have two machines writing the same SQLite
file over the network, and SQLite's locking can't be trusted across machines
there: the database could be damaged. So while `civex sync stdio` serves a
project, it holds `_civex/open-on-host.json` (the machine's name, refreshed
every `BEAT` seconds), and one started on another machine refuses until that
is `STALE` seconds old. Any number on the same machine is fine: SQLite's own
locking works there.

The file is never removed (another process on the same machine may still be
serving); it goes stale instead, so moving to another machine means waiting
`STALE` seconds after the last sync.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

FILE = "open-on-host.json"
BEAT = 30.0
STALE = 120.0


class OpenElsewhere(Exception):
    """The project is open on another machine."""


def this_host() -> str:
    return socket.gethostname()


def _holder(path: Path) -> tuple[str, float] | None:
    """The host named in the file and how many seconds ago it last said so."""
    try:
        host = str(json.loads(path.read_text("utf-8"))["host"])
        return host, time.time() - path.stat().st_mtime
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write(path: Path, host: str) -> None:
    tmp = path.with_name(f"{path.name}.{host}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"host": host, "pid": os.getpid()}), "utf-8")
    os.replace(tmp, path)


class HostLock:
    def __init__(self, civex_dir: Path, host: str | None = None) -> None:
        self._path = civex_dir / FILE
        self._host = host or this_host()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def acquire(self) -> None:
        """Take the project for this machine, or raise `OpenElsewhere`."""
        held = _holder(self._path)
        if held and held[0] != self._host and held[1] < STALE:
            raise OpenElsewhere(_elsewhere(*held))
        _write(self._path, self._host)
        # Two machines can both find it free and both write: whoever wrote
        # last holds it, and the other finds that out here.
        held = _holder(self._path)
        if held and held[0] != self._host:
            raise OpenElsewhere(_elsewhere(*held))
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()

    def _beat(self) -> None:
        while not self._stop.wait(BEAT):
            held = _holder(self._path)
            if held is None or held[0] == self._host:
                try:
                    _write(self._path, self._host)
                except OSError:
                    pass  # the drive hiccuped; the next beat tries again

    def release(self) -> None:
        self._stop.set()


def _elsewhere(host: str, age: float) -> str:
    wait = max(0, int(STALE - age))
    return (
        f"This project is open on {host} (another machine sharing its folder). "
        "Two machines writing its database at once could damage it: connect "
        f"through {host}, or, if nothing is using it there, try again in "
        f"{wait} seconds."
    )


__all__ = ["BEAT", "FILE", "STALE", "HostLock", "OpenElsewhere", "this_host"]
