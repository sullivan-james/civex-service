#!/usr/bin/env python3
"""Runs an installed civex the way a person would, before it is released.

    smoke_civex.py PATH/TO/civex[.exe] [--expect-version VERSION]

Stdlib only. A wheel or a frozen bundle can build cleanly and still be missing
files that are read from disk at runtime (the Alembic migrations once were
left out of the desktop bundle, so every download failed `civex init`), and
tests run from a checkout can't notice, because the checkout has every file.
So the release workflows run what they built: init a project, write to it,
serve it, and fetch the API and the UI. Everything happens in a temporary
home and project, never the runner's own.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PORT = 8765
STARTUP_SECONDS = 90


def run(exe: Path, *args: str, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        [str(exe), *args], cwd=cwd, env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.exit(f"`civex {' '.join(args)}` failed:\n{result.stdout}{result.stderr}")
    return result.stdout


def get(path: str) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=10) as r:
        return r.read().decode()


def stop(server: subprocess.Popen) -> None:
    """Stop the server and everything it started. On Windows the `civex.exe`
    an installer makes is a small launcher that runs Python as a child, so
    stopping the launcher alone left the server running (and its log open,
    which then can't be deleted)."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(server.pid)], capture_output=True
        )
    else:
        server.terminate()
    try:
        server.wait(timeout=15)
    except subprocess.TimeoutExpired:
        server.kill()
    # Waiting for the launcher isn't waiting for the server it started: on
    # Windows that one can still be letting go when the launcher has gone.
    # Gone means its port no longer answers; still answering is a real
    # failure, since the server didn't stop.
    deadline = time.monotonic() + 15
    while _answers():
        if time.monotonic() > deadline:
            sys.exit(
                f"civex serve is still running on port {PORT} after being stopped."
            )
        time.sleep(0.2)


def _answers() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1):
            return True
    except OSError:
        return False


def remove(folder: str) -> None:
    """Delete the temporary home and project. Windows can hold a stopped
    process's folders for a moment, so try for a while; a folder it still
    holds after that is reported, not a failure (every check has passed)."""
    deadline = time.monotonic() + 10
    while True:
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError as e:
            if time.monotonic() > deadline:
                print(f"warning: couldn't remove {folder}: {e}", file=sys.stderr)
                return
            time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exe", type=Path)
    parser.add_argument("--expect-version")
    args = parser.parse_args()
    exe = args.exe.resolve()
    tmp = tempfile.mkdtemp(prefix="civex-smoke-")
    try:
        home, project = Path(tmp, "home"), Path(tmp, "project")
        home.mkdir()
        project.mkdir()
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}

        reported = run(exe, "--version", cwd=project, env=env).strip()
        print(reported)
        if args.expect_version and reported.split()[-1] != args.expect_version:
            sys.exit(f"Expected civex {args.expect_version}, got: {reported}")
        run(exe, "init", cwd=project, env=env)
        run(exe, "schema", "create", "sample", cwd=project, env=env)

        server = subprocess.Popen(
            [str(exe), "serve", "--port", str(PORT)],
            cwd=project,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + STARTUP_SECONDS
            while True:
                try:
                    get("/health")
                    break
                except OSError:
                    if server.poll() is not None or time.monotonic() > deadline:
                        server.kill()
                        out = server.communicate()[0]
                        sys.exit(f"`civex serve` never answered:\n{out}")
                    time.sleep(1)
            if '"sample"' not in get("/api/schemas"):
                sys.exit("The API doesn't list the schema just created.")
            if "<title>civex</title>" not in get("/"):
                sys.exit("The web UI isn't in the bundle.")
        finally:
            stop(server)
    finally:
        remove(tmp)
    print("civex: init, schema, serve, API and UI all work")


if __name__ == "__main__":
    main()
