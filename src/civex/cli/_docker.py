from __future__ import annotations

import socket
import subprocess
import time

import typer

from civex.console import console

# container_exists/container_name/etc. re-exported here (unused-import ok)
# for cli/db.py and cli/init.py, which import Docker helpers from this module.
from civex.docker_manager import (  # noqa: F401
    ContainerRecoveryOutcome,
    container_exists,
    container_name,
    container_status,
    docker_available,
    docker_error_hint,
    ensure_container_running,
    volume_exists,
    wait_for_container_postgres,
)


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
    status = container_status(name)
    if status is not None:
        if status != "running":
            subprocess.run(["docker", "start", name], capture_output=True)
        return True, ""

    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"127.0.0.1:{port}:5432",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_DB=civex",
            "-v",
            f"{name}-pgdata:/var/lib/postgresql/data",
            "--restart",
            "unless-stopped",
            "postgres:16",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, ""


def teardown_pg_container(name: str) -> tuple[bool, str]:
    """Stop, remove, and delete the volume for a civex-managed postgres container.

    Returns (ok, error_message). Not an error if the container is already gone.
    """
    if not container_exists(name):
        return True, ""

    subprocess.run(["docker", "stop", name], capture_output=True)
    result = subprocess.run(["docker", "rm", name], capture_output=True, text=True)
    if result.returncode != 0:
        return False, result.stderr.strip()

    subprocess.run(["docker", "volume", "rm", f"{name}-pgdata"], capture_output=True)
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


def ensure_container_ready(project_name: str) -> None:
    """
    Pre-flight check for docker-managed projects, called before any CLI
    command that needs a working DB connection. Auto-starts a stopped
    container; prints a clear, actionable message and exits if the
    container — or worse, its data volume — is gone.
    """
    result = ensure_container_running(project_name)
    name = result.container_name

    if result.outcome in (
        ContainerRecoveryOutcome.READY,
        ContainerRecoveryOutcome.DOCKER_UNAVAILABLE,
    ):
        # READY: nothing to do. DOCKER_UNAVAILABLE: let the normal connection
        # attempt surface its own error rather than guessing why.
        return

    if result.outcome == ContainerRecoveryOutcome.START_FAILED:
        console.print(f"[error]Failed to start container '{name}'.[/error]")
        console.print(f"  [error]{result.detail}[/error]")
        raise typer.Exit(1)

    console.print(f"[error]PostgreSQL container '{name}' not found.[/error]")
    if result.outcome == ContainerRecoveryOutcome.MISSING_VOLUME_PRESENT:
        console.print("  Its data volume is still present, though.")
        console.print(
            "  Run [bold]civex db setup-docker[/bold] to recreate the container "
            "— your data will be reattached."
        )
    else:
        console.print(
            "  [bold]Its data volume is gone too — any data in this project's "
            "database is likely unrecoverable.[/bold]"
        )
        console.print(
            "  If you have a separate backup/dump, restore from that instead."
        )
        console.print(
            "  Otherwise, [bold]civex db setup-docker[/bold] will create a "
            "brand-new, EMPTY database at the same settings."
        )
    raise typer.Exit(1)
