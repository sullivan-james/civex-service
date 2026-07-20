"""
Database status, migration, and provisioning logic — the one place this is
implemented, shared by `civex db ...` CLI commands and the `/api/db` HTTP
routes so the two surfaces can't drift out of sync with each other.

Deliberately does not go through AppContext/build_local_context: every
function here must keep working even when the configured database itself is
unreachable or misconfigured — that's the whole point of exposing status,
"point at a different URL", and Docker setup/teardown as their own surface.
Callers (CLI prompts + console output, HTTP handlers + status codes) decide
how to present a ValidationError; nothing here prints or raises anything
else. Mirrors docker_manager.py's own "presentation-free, shared by cli and
server" split, one layer up.
"""

from __future__ import annotations

import socket
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from civex.config import Config, DBConfig, save_config
from civex.db.migrate import _MIGRATIONS_DIR, ensure_schema_current
from civex.docker_manager import (
    container_exists,
    container_name,
    container_status,
    docker_available,
    docker_error_hint,
    volume_exists,
    wait_for_container_postgres,
)
from civex.domain.exceptions import ValidationError

COMMON_PORTS = [5432, 5433]
SOCKET_DIRS = ["/var/run/postgresql", "/run/postgresql", "/tmp"]


# ---------------------------------------------------------------------------
# Driver detection
# ---------------------------------------------------------------------------


def detect_pg_driver() -> str | None:
    try:
        import psycopg  # noqa: F401

        return "psycopg"
    except ImportError:
        pass
    try:
        import psycopg2  # noqa: F401

        return "psycopg2"
    except ImportError:
        pass
    return None


def driver_install_hint() -> str:
    return "uv sync --extra postgres\npip install 'civex[postgres]'"


# ---------------------------------------------------------------------------
# Status shapes
# ---------------------------------------------------------------------------


@dataclass
class MigrationStatus:
    current_revision: str | None
    head_revision: str | None
    up_to_date: bool
    error: str | None = None  # set when the database itself couldn't be reached


@dataclass
class DockerStatus:
    name: str
    exists: bool
    running: bool
    volume_exists: bool


@dataclass
class DbStatus:
    url: str  # password redacted
    dialect: str  # "sqlite" | "postgresql"
    docker_managed: bool
    migration: MigrationStatus
    docker: DockerStatus | None


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.password:
        return url
    netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc))


# ---------------------------------------------------------------------------
# Connection testing / migration status
# ---------------------------------------------------------------------------


def test_connection(url: str) -> str | None:
    """Return None on success, or an error message string."""
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return None
    except Exception as exc:
        return str(exc)


def migration_status(url: str) -> MigrationStatus:
    """Never raises -- a status surface needs to keep working even when the
    configured database is unreachable, so a connection failure is reported
    as MigrationStatus.error rather than propagated."""
    engine = create_engine(url)
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    head = script.get_current_head()
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names()
            if "alembic_version" not in tables:
                return MigrationStatus(None, head, up_to_date=False)
            row = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            current = row[0] if row else None
    except Exception as exc:
        return MigrationStatus(None, head, up_to_date=False, error=str(exc))
    finally:
        engine.dispose()
    return MigrationStatus(current, head, up_to_date=current == head)


def apply_migrations(url: str) -> None:
    engine = create_engine(url)
    try:
        ensure_schema_current(engine)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Docker-managed Postgres
# ---------------------------------------------------------------------------


def docker_status(project_name: str) -> DockerStatus:
    name = container_name(project_name)
    status = container_status(name)
    return DockerStatus(
        name=name,
        exists=status is not None,
        running=status == "running",
        volume_exists=volume_exists(f"{name}-pgdata"),
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


def start_docker_container(name: str, port: int) -> tuple[bool, str]:
    """Start or create the civex postgres container. Returns (ok, error_message)."""
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


def wait_for_docker_postgres(port: int, timeout: int = 60) -> bool:
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
            try:
                s = socket.create_connection(("localhost", port), timeout=1)
                s.close()
                return True
            except OSError:
                pass
        time.sleep(1)
    return False


def teardown_docker_container(name: str) -> tuple[bool, str]:
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


def wait_for_docker_container_postgres(name: str, timeout: int = 60) -> bool:
    """Poll pg_isready inside the container — used by the setup wizard while the
    published port may not be reachable yet. Thin re-export of the
    docker_manager primitive so callers only need to import this module."""
    return wait_for_container_postgres(name, timeout=timeout)


# ---------------------------------------------------------------------------
# Local (non-Docker) PostgreSQL server probing — building blocks for the
# `civex db setup-postgres` interactive wizard. The prompting/orchestration
# itself stays CLI-only (it's a decision tree over a terminal), but the pure
# logic underneath lives here so nothing has to re-implement it.
# ---------------------------------------------------------------------------


def pg_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        result = subprocess.run(
            ["pg_isready", "-h", host, "-p", str(port)],
            capture_output=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def probe_local_postgres() -> tuple[str, int] | None:
    """Return (host, port) of the first local Postgres found, checking common ports."""
    for port in COMMON_PORTS:
        if pg_port_open("localhost", port):
            return "localhost", port
    return None


def find_socket_dir(port: int) -> str | None:
    """Return the Unix socket directory for the given port, or None."""
    for d in SOCKET_DIRS:
        if (Path(d) / f".s.PGSQL.{port}").exists():
            return d
    return None


def build_tcp_url(
    driver: str, user: str, password: str, host: str, port: int, dbname: str
) -> str:
    dialect = "postgresql+psycopg" if driver == "psycopg" else "postgresql+psycopg2"
    enc_user = urllib.parse.quote(user, safe="")
    if password:
        enc_pass = urllib.parse.quote(password, safe="")
        return f"{dialect}://{enc_user}:{enc_pass}@{host}:{port}/{dbname}"
    return f"{dialect}://{enc_user}@{host}:{port}/{dbname}"


def build_socket_url(
    driver: str, user: str, socket_dir: str, port: int, dbname: str
) -> str:
    dialect = "postgresql+psycopg" if driver == "psycopg" else "postgresql+psycopg2"
    enc_user = urllib.parse.quote(user, safe="")
    enc_dir = urllib.parse.quote(socket_dir, safe="")
    return f"{dialect}://{enc_user}@/{dbname}?host={enc_dir}&port={port}"


def create_pg_db(dbname: str, port: int, owner: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["createdb", dbname, "-p", str(port), "-O", owner],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr.strip()


def create_pg_user(user: str, port: int) -> tuple[bool, str]:
    result = subprocess.run(
        ["createuser", "--superuser", user, "-p", str(port)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr.strip()


def maybe_fix_and_connect(
    driver: str,
    user: str,
    port: int,
    dbname: str,
    socket_dir: str | None,
    err: str,
) -> str | None:
    """
    Inspect a connection error, attempt to fix it (create user/db), and
    return a working URL — or None if the problem can't be auto-fixed.
    """
    err_lower = err.lower()

    if "role" in err_lower and "does not exist" in err_lower:
        ok, _msg = create_pg_user(user, port)
        if not ok:
            return None

    if (
        "database" in err_lower
        and "does not exist" in err_lower
        or ("role" in err_lower and "does not exist" in err_lower)
    ):
        ok, _msg = create_pg_db(dbname, port, owner=user)
        if not ok:
            return None

        if socket_dir:
            url = build_socket_url(driver, user, socket_dir, port, dbname)
            if test_connection(url) is None:
                return url
        url = build_tcp_url(driver, user, "", "localhost", port, dbname)
        return url if test_connection(url) is None else None

    return None


def pg_install_hint() -> str:
    import platform

    system = platform.system()
    if system == "Linux":
        try:
            os_release = Path("/etc/os-release").read_text()
        except OSError:
            os_release = ""
        if "ubuntu" in os_release.lower() or "debian" in os_release.lower():
            return "sudo apt-get install -y postgresql\nsudo systemctl start postgresql"
        if (
            "fedora" in os_release.lower()
            or "rhel" in os_release.lower()
            or "centos" in os_release.lower()
        ):
            return (
                "sudo dnf install -y postgresql-server\n"
                "sudo postgresql-setup --initdb\n"
                "sudo systemctl start postgresql"
            )
        return "sudo apt-get install -y postgresql"
    if system == "Darwin":
        return "brew install postgresql@16\nbrew services start postgresql@16"
    return "https://www.postgresql.org/download/"


# ---------------------------------------------------------------------------
# High-level orchestration — status / migrate / set_url / docker setup+teardown
# ---------------------------------------------------------------------------


def get_status(config: Config) -> DbStatus:
    parsed = urllib.parse.urlparse(config.db.url)
    dialect = "sqlite" if parsed.scheme.startswith("sqlite") else "postgresql"
    docker = (
        docker_status(config.project_root.name) if config.db.docker_managed else None
    )
    return DbStatus(
        url=redact_url(config.db.url),
        dialect=dialect,
        docker_managed=config.db.docker_managed,
        migration=migration_status(config.db.url),
        docker=docker,
    )


def migrate(config: Config) -> DbStatus:
    apply_migrations(config.db.url)
    return get_status(config)


def set_url(config: Config, url: str) -> DbStatus:
    """Point civex at a different database. Tests the connection, saves it
    (clearing docker_managed — a manually supplied URL is no longer ours to
    manage), and migrates it to the current schema."""
    err = test_connection(url)
    if err:
        raise ValidationError(f"Could not connect: {err}")
    config.db = DBConfig(url=url, docker_managed=False)
    save_config(config)
    apply_migrations(url)
    return get_status(config)


def provision_docker_postgres(project_name: str) -> str:
    """Start (or reuse) a Docker Postgres container for *project_name* and
    return a working connection URL. Doesn't touch config — used both by
    setup_docker() below (an already-scaffolded project) and by `civex init`
    (which needs the URL before _civex/ exists to write config into)."""
    if not docker_available():
        raise ValidationError(f"Docker is not usable. {docker_error_hint()}")
    driver = detect_pg_driver()
    if driver is None:
        raise ValidationError(
            f"No PostgreSQL driver found (psycopg2 / psycopg). {driver_install_hint()}"
        )

    name = container_name(project_name)
    port = find_free_port(5432)

    ok, err = start_docker_container(name, port)
    if not ok:
        raise ValidationError(f"Failed to start container: {err}")
    if not wait_for_docker_postgres(port):
        raise ValidationError(
            "Container started but PostgreSQL didn't respond within 60s."
        )

    url = f"postgresql+psycopg2://postgres@localhost:{port}/civex"
    conn_err = test_connection(url)
    if conn_err:
        raise ValidationError(f"Could not connect: {conn_err}")
    return url


def setup_docker(config: Config, project_name: str | None = None) -> DbStatus:
    """Start (or reuse) this project's Docker-managed Postgres container,
    point config at it, and migrate."""
    url = provision_docker_postgres(project_name or config.project_root.name)
    config.db = DBConfig(url=url, docker_managed=True)
    save_config(config)
    apply_migrations(url)
    return get_status(config)


def teardown_docker(config: Config, project_name: str | None = None) -> None:
    name = container_name(project_name or config.project_root.name)
    ok, err = teardown_docker_container(name)
    if not ok:
        raise ValidationError(f"Failed to remove container: {err}")
