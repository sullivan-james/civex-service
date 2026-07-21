from __future__ import annotations

import getpass
import urllib.parse
from pathlib import Path

import typer

from civex.console import console
from civex.domain.exceptions import ValidationError
from civex.services import db_service

app = typer.Typer(help="Database management commands.")


# ---------------------------------------------------------------------------
# Interactive setup-postgres wizard — the prompting/decision-tree here is
# inherently CLI-only; the connection/provisioning logic it calls into lives
# in civex.services.db_service so the server's /api/db routes (which offer
# the non-interactive "give me a URL directly" path instead) share it.
# ---------------------------------------------------------------------------


def _run_wizard(driver: str) -> str:
    """Auto-detect a local Postgres server, try socket then TCP, auto-create
    missing user/db. Returns the resolved db_url."""
    current_user = getpass.getuser()

    console.print("\n[bold]Detecting local PostgreSQL server...[/bold]", end="  ")
    found = db_service.probe_local_postgres()

    if found:
        host, port = found
        console.print(f"[success]found[/success] [dim](port {port})[/dim]")
        socket_dir = db_service.find_socket_dir(port)

        if socket_dir:
            test_url = db_service.build_socket_url(
                driver, current_user, socket_dir, port, "postgres"
            )
            if db_service.test_connection(test_url) is None:
                dbname = typer.prompt(
                    f"  Connected as [bold]{current_user}[/bold] via socket. Database name",
                    default=Path.cwd().name,
                )
                return db_service.build_socket_url(
                    driver, current_user, socket_dir, port, dbname
                )

        tcp_test = db_service.build_tcp_url(
            driver, current_user, "", host, port, "postgres"
        )
        if db_service.test_connection(tcp_test) is None:
            dbname = typer.prompt(
                f"  Connected as [bold]{current_user}[/bold]. Database name",
                default=Path.cwd().name,
            )
            return db_service.build_tcp_url(
                driver, current_user, "", host, port, dbname
            )

        console.print(
            f"  [dim]Server found but could not auto-connect as [bold]{current_user}[/bold].[/dim]"
        )
        return _prompt_manual(
            driver, default_host=host, default_port=port, default_user=current_user
        )
    else:
        console.print("[dim]not found[/dim]")
        hint = db_service.pg_install_hint()
        console.print(
            f"\n  [dim]No PostgreSQL server detected on ports {db_service.COMMON_PORTS}.[/dim]"
        )
        console.print(f"  [dim]To install PostgreSQL:[/dim]\n  {hint}\n")
        console.print("  Or enter details for an existing server:")
        return _prompt_manual(driver)


def _prompt_manual(
    driver: str,
    default_host: str = "localhost",
    default_port: int = 5432,
    default_user: str = "",
) -> str:
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
    return db_service.build_tcp_url(driver, user, password, host, port, dbname)


def _print_project_summary(civex_dir: Path, is_new: bool) -> None:
    console.print(f"  Config     {civex_dir / 'config.toml'}")
    if is_new:
        console.print(f"  Objects    {civex_dir / 'objects'}")
        console.print(f"  Workflows  {civex_dir / 'workflows'}")
        console.print(f"  Plugins    {civex_dir / 'plugins'}")


def _ensure_project_dirs(root: Path) -> Path:
    civex_dir = root / "_civex"
    civex_dir.mkdir(parents=True)
    (civex_dir / "objects").mkdir()
    (civex_dir / "workflows").mkdir()
    (civex_dir / "plugins").mkdir()
    return civex_dir


def _load_or_new_config(root: Path, is_new: bool):
    """Load the existing config so db_service can overwrite just `.db` without
    losing remote/store/ai settings, or start a fresh minimal one for a
    brand-new project (there's nothing to preserve yet)."""
    from civex.config import Config, DBConfig, load_config

    if is_new:
        return Config(project_root=root, db=DBConfig(url=""), remote=None)
    return load_config()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("setup-docker")
def setup_docker() -> None:
    """Set up a Docker-managed PostgreSQL container for this civex project.

    Starts (or reuses) a named postgres:16 container, then updates
    _civex/config.toml with the new URL and creates all tables.
    Useful for migrating an existing SQLite project to PostgreSQL.
    """
    from civex.config import find_project_root, load_config

    root = find_project_root()
    project_name = root.name if root else Path.cwd().name

    # If neither the container nor its data volume exist, but this project
    # was previously docker-managed, we're about to create a brand-new,
    # EMPTY database — confirm before silently doing that.
    if root is not None:
        docker_status = db_service.docker_status(project_name)
        if not docker_status.exists and not docker_status.volume_exists:
            try:
                was_docker_managed = load_config().db.docker_managed
            except Exception:
                was_docker_managed = False
            if was_docker_managed:
                console.print(
                    f"[warning]No existing container or data volume found for "
                    f"'{docker_status.name}' — this will create a brand-new, EMPTY database.[/warning]"
                )
                typer.confirm("Continue?", abort=True)

    is_new = root is None
    if root is None:
        root = Path.cwd()
        console.print(f"\nInitialized civex project at [bold]{root}[/bold]")
    civex_dir = _ensure_project_dirs(root) if is_new else root / "_civex"
    config = _load_or_new_config(root, is_new)

    console.print("\nSetting up PostgreSQL via Docker...")
    try:
        status = db_service.setup_docker(config, project_name)
    except ValidationError as exc:
        console.print(f"[error]{exc}[/error]")
        raise typer.Exit(1)
    console.print("[success]OK[/success]")

    console.print("\n[success]Docker PostgreSQL setup complete.[/success]")
    console.print(f"  Database   {status.url}")
    _print_project_summary(civex_dir, is_new)


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
    from civex.config import find_project_root

    if not db_service.docker_available():
        console.print("[error]Docker is not usable.[/error]")
        raise typer.Exit(1)

    root = find_project_root()
    project_name = root.name if root else Path.cwd().name
    status = db_service.docker_status(project_name)

    if not status.exists:
        console.print(
            f"No Docker container named [bold]{status.name}[/bold] found — nothing to do."
        )
        return

    if not yes:
        console.print(
            f"[warning]This will permanently delete the [bold]{status.name}[/bold] "
            "container and its data volume.[/warning]"
        )
        typer.confirm("Proceed?", abort=True)

    console.print(f"Removing [bold]{status.name}[/bold]...", end="  ")
    ok, err = db_service.teardown_docker_container(status.name)
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
    from civex.config import find_project_root

    driver = db_service.detect_pg_driver()
    if driver is None:
        console.print("[error]No PostgreSQL driver found (psycopg2 / psycopg).[/error]")
        console.print(db_service.driver_install_hint())
        raise typer.Exit(1)

    if url:
        console.print(f"[dim]Using provided URL (driver: {driver})[/dim]")
        db_url = url
    else:
        db_url = _run_wizard(driver)

    console.print("\nTesting connection...", end="  ")
    err = db_service.test_connection(db_url)
    if err:
        console.print("[warning]retrying[/warning]")
        try:
            parsed = urllib.parse.urlparse(db_url)
            f_user = urllib.parse.unquote(parsed.username or getpass.getuser())
            f_port = parsed.port or 5432
            f_dbname = (parsed.path or "").lstrip("/")
            f_socket = db_service.find_socket_dir(f_port)
        except Exception:
            f_user, f_port, f_dbname, f_socket = getpass.getuser(), 5432, "civex", None
        db_url_fixed = db_service.maybe_fix_and_connect(
            driver, f_user, f_port, f_dbname, f_socket, err
        )
        if db_url_fixed:
            db_url = db_url_fixed
            console.print("Testing connection...", end="  ")
            err2 = db_service.test_connection(db_url)
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

    root = find_project_root()
    is_new = root is None
    if root is None:
        root = Path.cwd()
        console.print(f"\nInitialized civex project at [bold]{root}[/bold]")
    civex_dir = _ensure_project_dirs(root) if is_new else root / "_civex"
    config = _load_or_new_config(root, is_new)

    console.print("Creating tables...", end="    ")
    try:
        status = db_service.set_url(config, db_url)
    except ValidationError as exc:
        console.print("[error]FAILED[/error]")
        console.print(f"[error]{exc}[/error]")
        raise typer.Exit(1)
    console.print("[success]OK[/success]")

    console.print("\n[success]PostgreSQL setup complete.[/success]")
    console.print(f"  Database   {status.url}")
    _print_project_summary(civex_dir, is_new)
    console.print(
        "\n[dim]Note: credentials are stored in plaintext in _civex/config.toml.[/dim]"
    )


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
#
# civex applies pending migrations automatically the first time each process
# connects (see civex.db.migrate.ensure_schema_current, called from
# build_local_context). These commands are an explicit escape hatch: check
# status without touching the DB, or force the upgrade before a deploy
# instead of letting it happen implicitly on next connect.


@app.command("status")
def status() -> None:
    """Show the database's connection, migration, and (if applicable) Docker container status."""
    from civex.config import load_config

    config = load_config()
    info = db_service.get_status(config)

    console.print(f"[bold]Database[/bold]   {info.url}")
    console.print(f"[bold]Dialect[/bold]    {info.dialect}")
    console.print(
        f"[bold]Managed by[/bold] {'civex (Docker)' if info.docker_managed else 'you'}"
    )
    if info.migration.error:
        console.print(
            f"[bold]Schema[/bold]     [error]unreachable[/error] — {info.migration.error}"
        )
    elif info.migration.up_to_date:
        console.print(
            f"[bold]Schema[/bold]     [success]up to date[/success] at revision {info.migration.current_revision}"
        )
    elif info.migration.current_revision is None:
        console.print(
            "[bold]Schema[/bold]     [warning]not yet migrated[/warning] — "
            "will be created/stamped on next connect"
        )
    else:
        console.print(
            f"[bold]Schema[/bold]     [warning]pending migrations[/warning]: "
            f"at {info.migration.current_revision}, head is {info.migration.head_revision}"
        )

    if info.docker is not None:
        d = info.docker
        if not d.exists:
            state = (
                "[warning]container missing (data volume present)[/warning]"
                if d.volume_exists
                else "[error]container and data volume both missing[/error]"
            )
        else:
            state = (
                "[success]running[/success]"
                if d.running
                else "[warning]stopped[/warning]"
            )
        console.print(f"[bold]Container[/bold]  {d.name} — {state}")


@app.command("current")
def current() -> None:
    """Show the database's current migration revision and whether it's up to date."""
    from civex.config import load_config

    config = load_config()
    info = db_service.migration_status(config.db.url)

    if info.error:
        console.print(f"[error]Could not connect: {info.error}[/error]")
        raise typer.Exit(1)

    if info.current_revision is None:
        console.print(
            "[warning]Not yet migrated[/warning] — will be created/stamped on next connect."
        )
        raise typer.Exit(0)

    if info.up_to_date:
        console.print(
            f"[success]Up to date[/success] at revision {info.current_revision}"
        )
    else:
        console.print(
            f"[warning]Pending migrations[/warning]: at {info.current_revision}, head is {info.head_revision}"
        )


@app.command("migrate")
def migrate() -> None:
    """Apply any pending migrations now, instead of waiting for the next connect."""
    from civex.config import load_config

    config = load_config()
    console.print("Applying migrations...", end="    ")
    try:
        db_service.apply_migrations(config.db.url)
    except Exception as exc:
        console.print("[error]FAILED[/error]")
        console.print(f"[error]{exc}[/error]")
        raise typer.Exit(1)
    console.print("[success]OK[/success]")
