"""A stand-in for `ssh` in tests: no sshd, but the two things civex asks of it.

`-L 127.0.0.1:PORT:/socket` forwards each connection to a Unix socket, and the
last argument runs through the shell with this process's stdin. The host is
ignored (it is this machine). `FAKE_SSH_FAIL` makes it fail as ssh would.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while data := src.recv(65536):
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _forward(port: int, target: str) -> None:
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen()
    while True:
        local, _ = listener.accept()
        remote = socket.socket(socket.AF_UNIX)
        try:
            remote.connect(target)
        except OSError:
            local.close()
            continue
        threading.Thread(target=_pump, args=(local, remote), daemon=True).start()
        threading.Thread(target=_pump, args=(remote, local), daemon=True).start()


def main(argv: list[str]) -> int:
    fail = os.environ.get("FAKE_SSH_FAIL")
    if fail:
        print(fail, file=sys.stderr)
        return 255
    forward = argv[argv.index("-L") + 1]
    _, port, target = forward.split(":", 2)
    threading.Thread(target=_forward, args=(int(port), target), daemon=True).start()
    return subprocess.call(["sh", "-c", argv[-1]])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
