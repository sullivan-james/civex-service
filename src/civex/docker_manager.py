"""
Presentation-free Docker helpers for civex-managed PostgreSQL containers.

Shared by src/civex/cli/_docker.py (adds Rich console output + typer.Exit
for CLI commands) and src/civex/server/deps.py (adds a clean HTTP error for
API requests). Nothing here prints or raises anything but plain exceptions —
callers own how a result is surfaced to their audience.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from enum import Enum


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
        return (
            "docker info timed out — Docker may be starting up, try again in a moment"
        )


def container_name(project_name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", project_name).strip("-")
    return f"civex-{safe or 'project'}"


def container_status(name: str) -> str | None:
    """Docker's raw status string ('running', 'exited', ...), or None if missing."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def container_exists(name: str) -> bool:
    return container_status(name) is not None


def volume_exists(volume_name: str) -> bool:
    result = subprocess.run(
        ["docker", "volume", "inspect", volume_name], capture_output=True
    )
    return result.returncode == 0


def wait_for_container_postgres(name: str, timeout: int = 60) -> bool:
    """Poll pg_isready inside the container — no need to know its published port."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", "postgres"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True
        time.sleep(1)
    return False


class ContainerRecoveryOutcome(Enum):
    READY = "ready"  # already running, or successfully auto-started
    DOCKER_UNAVAILABLE = "docker_unavailable"  # docker daemon unreachable right now
    START_FAILED = "start_failed"  # container exists but wouldn't start/become ready
    MISSING_VOLUME_PRESENT = "missing_volume_present"  # container gone, volume intact
    MISSING_VOLUME_GONE = "missing_volume_gone"  # container AND volume both gone


@dataclass
class ContainerRecoveryResult:
    outcome: ContainerRecoveryOutcome
    container_name: str
    detail: str = ""


def ensure_container_running(project_name: str) -> ContainerRecoveryResult:
    """
    Check (and where possible, fix) a docker-managed project's Postgres
    container. Auto-starts a stopped container. Does not print or raise —
    callers decide how to present the outcome to their audience.
    """
    name = container_name(project_name)

    if not docker_available():
        return ContainerRecoveryResult(
            ContainerRecoveryOutcome.DOCKER_UNAVAILABLE, name
        )

    status = container_status(name)

    if status == "running":
        return ContainerRecoveryResult(ContainerRecoveryOutcome.READY, name)

    if status is not None:
        result = subprocess.run(
            ["docker", "start", name], capture_output=True, text=True
        )
        if result.returncode == 0 and wait_for_container_postgres(name):
            return ContainerRecoveryResult(ContainerRecoveryOutcome.READY, name)
        return ContainerRecoveryResult(
            ContainerRecoveryOutcome.START_FAILED,
            name,
            detail=result.stderr.strip() or "container did not become ready in time",
        )

    if volume_exists(f"{name}-pgdata"):
        return ContainerRecoveryResult(
            ContainerRecoveryOutcome.MISSING_VOLUME_PRESENT, name
        )
    return ContainerRecoveryResult(ContainerRecoveryOutcome.MISSING_VOLUME_GONE, name)
