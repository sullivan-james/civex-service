from __future__ import annotations

import getpass
import socket
import subprocess
import urllib.parse
from pathlib import Path

import typer

from civex.cli._pgdriver import detect_pg_driver, driver_install_hint
from civex.console import console

app = typer.Typer(help="Database management commands.")

_COMMON_PORTS = [5432, 5433]
_SOCKET_DIRS = ["/var/run/postgresql", "/run/postgresql", "/tmp"]


# ---------------------------------------------------------------------------
# Local server detection
# ---------------------------------------------------------------------------


def _pg_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
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


def _probe_local() -> tuple[str, int] | None:
    """Return (host, port) of the first local Postgres found, checking common ports."""
    for port in _COMMON_PORTS:
        if _pg_port_open("localhost", port):
            return "localhost", port
    return None


def _find_socket_dir(port: int) -> str | None:
    """Return the Unix socket directory for the given port, or None."""
    for d in _SOCKET_DIRS:
        if (Path(d) / f".s.PGSQL.{port}").exists():
            return d
    return None


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


def _tcp_url(
    driver: str, user: str, password: str, host: str, port: int, dbname: str
) -> str:
    dialect = "postgresql+psycopg" if driver == "psycopg" else "postgresql+psycopg2"
    enc_user = urllib.parse.quote(user, safe="")
    if password:
        enc_pass = urllib.parse.quote(password, safe="")
        return f"{dialect}://{enc_user}:{enc_pass}@{host}:{port}/{dbname}"
    return f"{dialect}://{enc_user}@{host}:{port}/{dbname}"


def _socket_url(driver: str, user: str, socket_dir: str, port: int, dbname: str) -> str:
    dialect = "postgresql+psycopg" if driver == "psycopg" else "postgresql+psycopg2"
    enc_user = urllib.parse.quote(user, safe="")
    enc_dir = urllib.parse.quote(socket_dir, safe="")
    return f"{dialect}://{enc_user}@/{dbname}?host={enc_dir}&port={port}"


# ---------------------------------------------------------------------------
# Connection testing
# ---------------------------------------------------------------------------


def _test_connection(url: str) -> str | None:
    """Return None on success, or an error message string."""
    from sqlalchemy import create_engine, text

    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return None
    except Exception as exc:
        return str(exc)


# ---------------------------------------------------------------------------
# Database / user provisioning via CLI tools
# ---------------------------------------------------------------------------


def _createdb(dbname: str, port: int, owner: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["createdb", dbname, "-p", str(port), "-O", owner],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr.strip()


def _createuser(user: str, port: int) -> tuple[bool, str]:
    result = subprocess.run(
        ["createuser", "--superuser", user, "-p", str(port)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr.strip()


def _maybe_fix_and_connect(
    driver: str,
    user: str,
    port: int,
    dbname: str,
    socket_dir: str | None,
    err: str,
) -> str | None:
    """
    Inspect the error, attempt to fix it (create user/db), and return a
    working URL — or None if the problem can't be auto-fixed.
    """
    err_lower = err.lower()

    # ---- role doesn't exist → createuser --------------------------------
    if "role" in err_lower and "does not exist" in err_lower:
        console.print(f"  Role [bold]{user}[/bold] not found. Creating it...", end="  ")
        ok, msg = _createuser(user, port)
        if not ok:
            console.print("[error]FAILED[/error]")
            console.print(f"  [dim]{msg}[/dim]")
            return None
        console.print("[success]OK[/success]")
        # Fall through — user now exists, may still need the DB

    # ---- database doesn't exist → createdb ------------------------------
    if (
        "database" in err_lower
        and "does not exist" in err_lower
        or ("role" in err_lower and "does not exist" in err_lower)
    ):
        console.print(
            f"  Database [bold]{dbname}[/bold] not found. Creating it...", end="  "
        )
        ok, msg = _createdb(dbname, port, owner=user)
        if not ok:
            console.print("[error]FAILED[/error]")
            console.print(f"  [dim]{msg}[/dim]")
            return None
        console.print("[success]OK[/success]")

        # Retry via socket (peer auth) or TCP
        if socket_dir:
            url = _socket_url(driver, user, socket_dir, port, dbname)
            if _test_connection(url) is None:
                return url
        url = _tcp_url(driver, user, "", "localhost", port, dbname)
        return url if _test_connection(url) is None else None

    return None


# ---------------------------------------------------------------------------
# OS-level installation hints
# ---------------------------------------------------------------------------


def _pg_install_hint() -> str:
    import platform

    system = platform.system()
    if system == "Linux":
        try:
            os_release = Path("/etc/os-release").read_text()
        except OSError:
            os_release = ""
        if "ubuntu" in os_release.lower() or "debian" in os_release.lower():
            return (
                "  sudo apt-get install -y postgresql\n"
                "  sudo systemctl start postgresql"
            )
        if (
            "fedora" in os_release.lower()
            or "rhel" in os_release.lower()
            or "centos" in os_release.lower()
        ):
            return (
                "  sudo dnf install -y postgresql-server\n"
                "  sudo postgresql-setup --initdb\n"
                "  sudo systemctl start postgresql"
            )
        return "  sudo apt-get install -y postgresql"
    if system == "Darwin":
        return "  brew install postgresql@16\n  brew services start postgresql@16"
    return "  https://www.postgresql.org/download/"


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@app.command("setup-docker")
def setup_docker() -> None:
    """Set up a Docker-managed PostgreSQL container for this civex project.

    Starts (or reuses) a named postgres:16 container, then updates
    _civex/config.toml with the new URL and creates all tables.
    Useful for migrating an existing SQLite project to PostgreSQL.
    """
    from civex.cli._docker import (
        container_exists,
        container_name,
        docker_available,
        setup_docker_postgres,
        volume_exists,
    )
    from civex.config import Config, DBConfig, find_project_root, save_config
    from civex.db.migrate import ensure_schema_current
    from sqlalchemy import create_engine

    # Ensure Docker is running
    if not docker_available():
        from civex.cli._docker import docker_error_hint

        console.print("[error]Docker is not usable.[/error]")
        console.print(f"  {docker_error_hint()}")
        raise typer.Exit(1)

    # Ensure a postgres driver is installed
    driver = detect_pg_driver()
    if driver is None:
        console.print("[error]No PostgreSQL driver found (psycopg2 / psycopg).[/error]")
        console.print(driver_install_hint())
        raise typer.Exit(1)

    # Determine project name for the container
    root = find_project_root()
    project_name = root.name if root else Path.cwd().name

    # If neither the container nor its data volume exist, but this project
    # was previously docker-managed, we're about to create a brand-new,
    # EMPTY database — confirm before silently doing that.
    name = container_name(project_name)
    if (
        root is not None
        and not container_exists(name)
        and not volume_exists(f"{name}-pgdata")
    ):
        try:
            from civex.config import load_config

            was_docker_managed = load_config().db.docker_managed
        except Exception:
            was_docker_managed = False
        if was_docker_managed:
            console.print(
                f"[warning]No existing container or data volume found for "
                f"'{name}' — this will create a brand-new, EMPTY database.[/warning]"
            )
            typer.confirm("Continue?", abort=True)

    db_url = setup_docker_postgres(project_name)
    if db_url is None:
        raise typer.Exit(1)

    # Test the connection
    console.print("\nTesting connection...", end="  ")
    err = _test_connection(db_url)
    if err:
        console.print("[error]FAILED[/error]")
        console.print(f"[error]{err}[/error]")
        raise typer.Exit(1)
    console.print("[success]OK[/success]")

    # Write config (create _civex structure if this is a new project)
    is_new = root is None
    if root is None:
        root = Path.cwd()
        civex_dir = root / "_civex"
        civex_dir.mkdir(parents=True)
        (civex_dir / "objects").mkdir()
        (civex_dir / "workflows").mkdir()
        (civex_dir / "plugins").mkdir()
        console.print(f"\nInitialized civex project at [bold]{root}[/bold]")
    else:
        civex_dir = root / "_civex"

    try:
        from civex.config import load_config

        existing = load_config()
        config = Config(
            project_root=root,
            db=DBConfig(url=db_url, docker_managed=True),
            remote=existing.remote,
        )
    except Exception:
        config = Config(
            project_root=root, db=DBConfig(url=db_url, docker_managed=True), remote=None
        )

    save_config(config)

    # Create / migrate tables
    console.print("Creating tables...", end="    ")
    try:
        engine = create_engine(db_url)
        ensure_schema_current(engine)
        engine.dispose()
        console.print("[success]OK[/success]")
    except Exception as exc:
        console.print("[error]FAILED[/error]")
        console.print(f"[error]{exc}[/error]")
        raise typer.Exit(1)

    import urllib.parse

    parsed = urllib.parse.urlparse(db_url)
    console.print("\n[success]Docker PostgreSQL setup complete.[/success]")
    console.print(
        f"  Database   postgresql://{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
    )
    console.print(f"  Config     {civex_dir / 'config.toml'}")
    if is_new:
        console.print(f"  Objects    {civex_dir / 'objects'}")
        console.print(f"  Workflows  {civex_dir / 'workflows'}")
        console.print(f"  Plugins    {civex_dir / 'plugins'}")


@app.command("teardown")
def teardown(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
) -> None:
    """Stop and remove this project's Docker-managed PostgreSQL container and its data.

    civex init / civex db setup-docker create a per-project container that
    keeps running (--restart unless-stopped) even after the project
    directory is deleted. Run this before abandoning a project to avoid
    leaving it behind. Does nothing to a manually-managed PostgreSQL server.
    """
    from civex.cli._docker import (
        container_exists,
        docker_available,
        teardown_pg_container,
    )
    from civex.cli._docker import container_name as _container_name
    from civex.config import find_project_root

    if not docker_available():
        console.print("[error]Docker is not usable.[/error]")
        raise typer.Exit(1)

    root = find_project_root()
    project_name = root.name if root else Path.cwd().name
    name = _container_name(project_name)

    if not container_exists(name):
        console.print(
            f"No Docker container named [bold]{name}[/bold] found — nothing to do."
        )
        return

    if not yes:
        console.print(
            f"[warning]This will permanently delete the [bold]{name}[/bold] "
            "container and its data volume.[/warning]"
        )
        typer.confirm("Proceed?", abort=True)

    console.print(f"Removing [bold]{name}[/bold]...", end="  ")
    ok, err = teardown_pg_container(name)
    if not ok:
        console.print("[error]FAILED[/error]")
        console.print(f"[error]{err}[/error]")
        raise typer.Exit(1)
    console.print("[success]OK[/success]")
    console.print(
        "[dim]_civex/config.toml still points at this container — run "
        "`civex db setup-docker` or `--sqlite` if you want to keep using this project.[/dim]"
    )


@app.command("setup-postgres")
def setup_postgres(
    url: str | None = typer.Option(
        None,
        "--url",
        help="Full PostgreSQL URL — skips all prompts. "
        "Example: postgresql+psycopg2://user:pass@host:5432/dbname",
        envvar="CIVEX_DB_URL",
    ),
) -> None:
    """Configure civex to use a PostgreSQL database.

    Auto-detects a local PostgreSQL server, creates the database and user role
    if needed, then writes the URL to _civex/config.toml and creates all tables.
    Pass [bold]--url[/bold] to skip interactive prompts (useful in scripts/CI).
    """
    from civex.config import Config, DBConfig, find_project_root, save_config
    from civex.db.migrate import ensure_schema_current
    from sqlalchemy import create_engine

    # ---- Phase 1: Ensure a Python driver ------------------------------------
    driver = detect_pg_driver()
    if driver is None:
        console.print("[error]No PostgreSQL driver found (psycopg2 / psycopg).[/error]")
        console.print(driver_install_hint())
        raise typer.Exit(1)

    # ---- Phase 2: Resolve a working DB URL ----------------------------------
    if url:
        console.print(f"[dim]Using provided URL (driver: {driver})[/dim]")
        db_url = url
        try:
            parsed = urllib.parse.urlparse(url)
            display = f"{parsed.hostname or '?'}:{parsed.port or 5432}/{(parsed.path or '').lstrip('/')}"
        except Exception:
            display = url
    else:
        db_url, display = _run_wizard(driver)

    # ---- Phase 3: Final connection test + auto-fix if still broken ----------
    console.print("\nTesting connection...", end="  ")
    err = _test_connection(db_url)
    if err:
        console.print("[warning]retrying[/warning]")
        # Try to parse enough context to auto-fix
        try:
            parsed = urllib.parse.urlparse(db_url)
            f_user = urllib.parse.unquote(parsed.username or getpass.getuser())
            f_port = parsed.port or 5432
            f_dbname = (parsed.path or "").lstrip("/")
            f_socket = _find_socket_dir(f_port)
        except Exception:
            f_user, f_port, f_dbname, f_socket = getpass.getuser(), 5432, "civex", None
        db_url_fixed = _maybe_fix_and_connect(
            driver, f_user, f_port, f_dbname, f_socket, err
        )
        if db_url_fixed:
            db_url = db_url_fixed
            display = f"localhost:{f_port}/{f_dbname}"
            console.print("Testing connection...", end="  ")
            err2 = _test_connection(db_url)
            if err2:
                console.print("[error]FAILED[/error]")
                console.print(f"[error]{err2}[/error]")
                raise typer.Exit(1)
            console.print("[success]OK[/success]")
        else:
            console.print("[error]FAILED[/error]")
            console.print(f"[error]{err}[/error]")
            raise typer.Exit(1)
    else:
        console.print("[success]OK[/success]")

    # ---- Phase 4: Write config ----------------------------------------------
    root = find_project_root()
    is_new = root is None
    if root is None:
        root = Path.cwd()
        civex_dir = root / "_civex"
        civex_dir.mkdir(parents=True)
        (civex_dir / "objects").mkdir()
        (civex_dir / "workflows").mkdir()
        (civex_dir / "plugins").mkdir()
        console.print(f"\nInitialized civex project at [bold]{root}[/bold]")
    else:
        civex_dir = root / "_civex"

    try:
        from civex.config import load_config

        existing = load_config()
        config = Config(
            project_root=root, db=DBConfig(url=db_url), remote=existing.remote
        )
    except Exception:
        config = Config(project_root=root, db=DBConfig(url=db_url), remote=None)

    save_config(config)

    # ---- Phase 5: Create tables ---------------------------------------------
    console.print("Creating tables...", end="    ")
    try:
        engine = create_engine(db_url)
        ensure_schema_current(engine)
        engine.dispose()
        console.print("[success]OK[/success]")
    except Exception as exc:
        console.print("[error]FAILED[/error]")
        console.print(f"[error]{exc}[/error]")
        raise typer.Exit(1)

    # ---- Summary ------------------------------------------------------------
    console.print("\n[success]PostgreSQL setup complete.[/success]")
    console.print(f"  Database   postgresql://{display}")
    console.print(f"  Config     {civex_dir / 'config.toml'}")
    if is_new:
        console.print(f"  Objects    {civex_dir / 'objects'}")
        console.print(f"  Workflows  {civex_dir / 'workflows'}")
        console.print(f"  Plugins    {civex_dir / 'plugins'}")
    console.print(
        "\n[dim]Note: credentials are stored in plaintext in _civex/config.toml.[/dim]"
    )


def _run_wizard(driver: str) -> tuple[str, str]:
    """
    Interactive path: auto-detect local Postgres, try socket then TCP,
    auto-create missing user/db. Returns (db_url, display_string).
    """
    current_user = getpass.getuser()

    console.print("\n[bold]Detecting local PostgreSQL server...[/bold]", end="  ")
    found = _probe_local()

    if found:
        host, port = found
        console.print(f"[success]found[/success] [dim](port {port})[/dim]")
        socket_dir = _find_socket_dir(port)

        # Prefer socket (peer auth → no password)
        if socket_dir:
            test_url = _socket_url(driver, current_user, socket_dir, port, "postgres")
            if _test_connection(test_url) is None:
                dbname = typer.prompt(
                    f"  Connected as [bold]{current_user}[/bold] via socket. Database name",
                    default=Path.cwd().name,
                )
                db_url = _socket_url(driver, current_user, socket_dir, port, dbname)
                return db_url, f"localhost:{port}/{dbname}"

        # Socket didn't work or doesn't exist — try TCP
        tcp_test = _tcp_url(driver, current_user, "", host, port, "postgres")
        if _test_connection(tcp_test) is None:
            dbname = typer.prompt(
                f"  Connected as [bold]{current_user}[/bold]. Database name",
                default=Path.cwd().name,
            )
            db_url = _tcp_url(driver, current_user, "", host, port, dbname)
            return db_url, f"{host}:{port}/{dbname}"

        # Connected to server but auth needs credentials
        console.print(
            f"  [dim]Server found but could not auto-connect as [bold]{current_user}[/bold].[/dim]"
        )
        return _prompt_manual(
            driver, default_host=host, default_port=port, default_user=current_user
        )
    else:
        console.print("[dim]not found[/dim]")
        hint = _pg_install_hint()
        console.print(
            f"\n  [dim]No PostgreSQL server detected on ports {_COMMON_PORTS}.[/dim]"
        )
        console.print(f"  [dim]To install PostgreSQL:[/dim]\n{hint}\n")
        console.print("  Or enter details for an existing server:")
        return _prompt_manual(driver)


def _prompt_manual(
    driver: str,
    default_host: str = "localhost",
    default_port: int = 5432,
    default_user: str = "",
) -> tuple[str, str]:
    """Collect host/port/dbname/user/password interactively."""
    if not default_user:
        default_user = getpass.getuser()
    console.print("")
    host = typer.prompt("  Host", default=default_host)
    port = typer.prompt("  Port", default=default_port, type=int)
    dbname = typer.prompt("  Database name", default=Path.cwd().name)
    user = typer.prompt("  User", default=default_user)
    password = typer.prompt(
        "  Password (blank for passwordless)", default="", hide_input=True
    )
    return _tcp_url(
        driver, user, password, host, port, dbname
    ), f"{host}:{port}/{dbname}"


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
#
# civex applies pending migrations automatically the first time each process
# connects (see civex.db.migrate.ensure_schema_current, called from
# build_local_context). These commands are an explicit escape hatch: check
# status without touching the DB, or force the upgrade before a deploy
# instead of letting it happen implicitly on next connect.


@app.command("current")
def current() -> None:
    """Show the database's current migration revision and whether it's up to date."""
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    from civex.config import load_config
    from civex.db.migrate import _MIGRATIONS_DIR

    config = load_config()
    engine = create_engine(config.db.url)

    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    head = script.get_current_head()

    with engine.connect() as connection:
        tables = inspect(connection).get_table_names()
        if "alembic_version" not in tables:
            console.print(
                "[warning]Not yet migrated[/warning] — will be created/stamped on next connect."
            )
            raise typer.Exit(0)
        row = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        current_rev = row[0] if row else None

    if current_rev == head:
        console.print(f"[success]Up to date[/success] at revision {current_rev}")
    else:
        console.print(
            f"[warning]Pending migrations[/warning]: at {current_rev}, head is {head}"
        )


@app.command("migrate")
def migrate() -> None:
    """Apply any pending migrations now, instead of waiting for the next connect."""
    from sqlalchemy import create_engine

    from civex.config import load_config
    from civex.db.migrate import ensure_schema_current

    config = load_config()
    engine = create_engine(config.db.url)
    console.print("Applying migrations...", end="    ")
    try:
        ensure_schema_current(engine)
    except Exception as exc:
        console.print("[error]FAILED[/error]")
        console.print(f"[error]{exc}[/error]")
        raise typer.Exit(1)
    console.print("[success]OK[/success]")
