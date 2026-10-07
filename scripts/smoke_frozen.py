#!/usr/bin/env python3
"""Runs a frozen civex CLI the way a person without Python would.

    smoke_frozen.py PATH/TO/civex[.exe]

Stdlib only. A bundle can build cleanly and still be missing files that are
read from disk at runtime (the Alembic migrations once were, so every desktop
download failed `civex init`), so CI runs the binary instead of trusting the
build: init a project, write to it, serve it, and fetch the API and the UI.
Everything happens in a temporary home and project, never the runner's own.
"""

from __future__ import annotations

import os
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


def main() -> None:
    exe = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        home, project = Path(tmp, "home"), Path(tmp, "project")
        home.mkdir()
        project.mkdir()
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}

        print(run(exe, "--version", cwd=project, env=env).strip())
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
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
    print("frozen civex: init, schema, serve, API and UI all work")


if __name__ == "__main__":
    main()
