from __future__ import annotations

import re
import socket
import subprocess
import time

from civex.console import console


def docker_available() -> bool:
    """Return True if Docker is installed and the current user can reach the socket."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
    except subprocess.TimeoutExpired:
        return False


def docker_error_hint() -> str:
    """Return a human-readable reason why Docker isn't usable."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return ""
        combined = (result.stdout + result.stderr).lower()
        if "permission denied" in combined and "docker.sock" in combined:
            import getpass
            user = getpass.getuser()
            return (
                f"Permission denied on the Docker socket.\n"
                f"  Fix:  sudo usermod -aG docker {user}\n"
                f"  Then: newgrp docker    (or log out and back in)"
            )
        if "cannot connect" in combined or "is the docker daemon running" in combined:
            return "Docker daemon is not running. Start Docker Desktop or run: sudo systemctl start docker"
        return result.stderr.strip() or "docker info returned a non-zero exit code"
    except FileNotFoundError:
        return "Docker is not installed. See https://www.docker.com/products/docker-desktop"
    except subprocess.TimeoutExpired:
        return "docker info timed out — Docker may be starting up, try again in a moment"


def container_name(project_name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", project_name).strip("-")
    return f"civex-{safe or 'project'}"


def find_free_port(preferred: int = 5432) -> int:
    try:
        s = socket.socket()
        s.bind(("", preferred))
        s.close()
        return preferred
    except OSError:
        s = socket.socket()
        s.bind(("", 0))
        port = s.getsockname()[1]
        s.close()
        return port


def start_pg_container(name: str, port: int) -> tuple[bool, str]:
    """Start or create the civex postgres container. Returns (ok, error_message)."""
    # Reuse existing container if it already exists
    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", name],
        capture_output=True,
        text=True,
    )
    if inspect.returncode == 0:
        status = inspect.stdout.strip()
        if status != "running":
            subprocess.run(["docker", "start", name], capture_output=True)
        return True, ""

    result = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", name,
            "-p", f"{port}:5432",
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e", "POSTGRES_DB=civex",
            "-v", f"{name}-pgdata:/var/lib/postgresql/data",
            "--restart", "unless-stopped",
            "postgres:16",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, ""


def wait_for_postgres(port: int, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = subprocess.run(
                ["pg_isready", "-h", "localhost", "-p", str(port), "-q"],
                capture_output=True,
                timeout=3,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # pg_isready not available — fall back to raw socket probe
            try:
                s = socket.create_connection(("localhost", port), timeout=1)
                s.close()
                return True
            except OSError:
                pass
        time.sleep(1)
    return False


def setup_docker_postgres(project_name: str) -> str | None:
    """
    Spin up (or reuse) a Docker postgres container for this project.
    Returns a SQLAlchemy URL on success, None on failure.
    """
    name = container_name(project_name)
    port = find_free_port(5432)

    console.print("\nSetting up PostgreSQL via Docker...")
    console.print(f"  Starting container [bold]{name}[/bold]...", end="  ")

    ok, err = start_pg_container(name, port)
    if not ok:
        console.print("[error]FAILED[/error]")
        console.print(f"  [dim]{err}[/dim]")
        return None
    console.print("[success]OK[/success]")

    console.print("  Waiting for PostgreSQL...", end="         ")
    if not wait_for_postgres(port):
        console.print("[error]timed out[/error]")
        console.print(
            "  [dim]Container started but postgres didn't respond within 60s.[/dim]"
        )
        return None
    console.print("[success]OK[/success]")

    return f"postgresql+psycopg2://postgres@localhost:{port}/civex"
