"""Moving a project's data to another database.

One operation -- `run_move(config, target)` -- whatever the two ends are:
SQLite, Docker-managed PostgreSQL or a PostgreSQL server, in any direction. A
target is only a way of getting a URL (`resolve_target`); everything after that
is the same: check the target is empty, bring both to the same schema revision,
copy and verify (civex.db.move), and only then point config at the new database.
The old database is never modified or removed, so a move can always be undone
by switching back (`revert`).

Like db_service this deliberately bypasses AppContext: it has to work when the
configured database is the very thing being replaced. Presentation-free --
callers (CLI, HTTP) decide how to show progress and errors.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from civex.config import Config, DBConfig, save_config
from civex.db import move as engine_move
from civex.db.engine import enable_sqlite_foreign_keys
from civex.domain.exceptions import ValidationError
from civex.services import db_service

Kind = Literal["sqlite", "docker", "postgres"]
Status = Literal["running", "done", "failed", "cancelled"]

HISTORY_FILE = "db-moves.json"

# Rough copy speed, for the "about N minutes" estimate shown before a move.
ROWS_PER_SECOND = 15_000

# One move at a time per process: two copies into one target would corrupt it.
_active = threading.Lock()


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


@dataclass
class TargetSpec:
    """Where to move to. `kind` picks how the URL is obtained:

    sqlite    a new file in the project (or `path`)
    docker    this project's Civex-managed PostgreSQL container
    postgres  a server you run: `url`, or host/port/database/user/password
    """

    kind: Kind
    url: str | None = None
    path: str | None = None
    host: str | None = None
    port: int = 5432
    database: str | None = None
    user: str | None = None
    password: str | None = None


def postgres_url(spec: TargetSpec) -> str:
    """The connection URL for a PostgreSQL server given as separate fields, so
    nobody has to hand-write (and hand-escape) one."""
    if spec.url:
        return spec.url
    if not spec.host or not spec.database:
        raise ValidationError(
            "A PostgreSQL server needs at least a host and a database."
        )
    driver = db_service.detect_pg_driver()
    if driver is None:
        raise ValidationError(
            f"No PostgreSQL driver found (psycopg2 / psycopg). {db_service.driver_install_hint()}"
        )
    user = urllib.parse.quote(spec.user or "", safe="")
    password = urllib.parse.quote(spec.password or "", safe="")
    auth = f"{user}:{password}@" if password else f"{user}@" if user else ""
    return (
        f"postgresql+{driver}://{auth}{spec.host}:{spec.port}/"
        f"{urllib.parse.quote(spec.database, safe='')}"
    )


def _new_sqlite_path(config: Config, spec: TargetSpec) -> Path:
    if spec.path:
        return Path(spec.path).expanduser().resolve()
    directory = config.project_root / "_civex"
    first = directory / "civex.db"
    if not first.exists():
        return first
    # Never overwrite or reuse a database file: a move always lands in a new one.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return directory / f"civex-{stamp}.db"


@dataclass
class ResolvedTarget:
    kind: Kind
    url: str
    docker_managed: bool
    label: str  # "SQLite file", "Docker PostgreSQL", "PostgreSQL server"


def resolve_target(
    config: Config, spec: TargetSpec, *, provision: bool
) -> ResolvedTarget:
    """Turn a TargetSpec into a URL. With `provision=False` nothing is created
    or started (a preview); with True a Docker container is started."""
    if spec.kind == "sqlite":
        path = _new_sqlite_path(config, spec)
        if path.exists():
            raise ValidationError(f"{path} already exists. Pick a new file name.")
        return ResolvedTarget("sqlite", f"sqlite:///{path}", False, "SQLite file")
    if spec.kind == "docker":
        if provision:
            url = db_service.provision_docker_postgres(config.project_root.name)
        else:
            status = db_service.docker_status(config.project_root.name)
            if not status.running:
                url = ""  # not started yet: nothing to inspect
            else:
                url = _running_docker_url(config)
        return ResolvedTarget("docker", url, True, "Docker PostgreSQL")
    if spec.kind == "postgres":
        return ResolvedTarget(
            "postgres", postgres_url(spec), False, "PostgreSQL server"
        )
    raise ValidationError(f"Unknown destination '{spec.kind}'.")


def _running_docker_url(config: Config) -> str:
    """The URL of an already-running project container, without starting or
    creating anything."""
    from civex.docker_manager import container_host_port, container_name

    port = container_host_port(container_name(config.project_root.name))
    return f"postgresql+psycopg2://postgres@localhost:{port}/civex" if port else ""


# ---------------------------------------------------------------------------
# Summaries and preflight
# ---------------------------------------------------------------------------


def _engine(url: str) -> Engine:
    return enable_sqlite_foreign_keys(create_engine(url))


@dataclass
class DatabaseSummary:
    label: str
    dialect: str
    location: str  # URL with the password hidden
    reachable: bool = True
    error: str | None = None
    records: int = 0
    rows: int = 0
    tables: dict[str, int] = field(default_factory=dict)
    size_bytes: int | None = None


def _label(url: str, docker_managed: bool) -> tuple[str, str]:
    dialect = "sqlite" if url.startswith("sqlite") else "postgresql"
    if dialect == "sqlite":
        return "SQLite file", dialect
    return ("Docker PostgreSQL" if docker_managed else "PostgreSQL server"), dialect


def summarize(url: str, docker_managed: bool = False) -> DatabaseSummary:
    """What is in the database at `url`. Never raises: an unreachable database
    comes back with `reachable=False` and the reason."""
    label, dialect = _label(url, docker_managed)
    out = DatabaseSummary(label, dialect, db_service.redact_url(url))
    if not url:
        out.reachable = False
        out.error = "Not started yet"
        return out
    engine = None
    try:
        if dialect == "sqlite":
            path = Path(urllib.parse.urlparse(url).path)
            if not path.exists():
                # Connecting would create the file -- a preview mustn't.
                return out
        engine = _engine(url)
        out.tables = engine_move.row_counts(engine)
        out.rows = sum(out.tables.values())
        out.records = out.tables.get("records", 0)
        if dialect == "sqlite":
            path = Path(urllib.parse.urlparse(url).path)
            out.size_bytes = path.stat().st_size if path.exists() else None
        else:
            with engine.connect() as conn:
                out.size_bytes = conn.execute(
                    text("SELECT pg_database_size(current_database())")
                ).scalar_one()
    except Exception as exc:
        out.reachable, out.error = False, str(exc).splitlines()[0]
    finally:
        if engine is not None:
            engine.dispose()
    return out


@dataclass
class Preflight:
    source: DatabaseSummary
    target: DatabaseSummary
    target_label: str
    problems: list[str] = field(default_factory=list)  # block the move
    warnings: list[str] = field(default_factory=list)
    estimate_seconds: int = 0

    @property
    def can_proceed(self) -> bool:
        return not self.problems


def preflight(config: Config, spec: TargetSpec) -> Preflight:
    """What a move would do, and whether it can -- with no side effects (no
    container is started, nothing is written)."""
    source = summarize(config.db.url, config.db.docker_managed)
    problems: list[str] = []
    warnings: list[str] = []
    try:
        resolved = resolve_target(config, spec, provision=False)
    except ValidationError as exc:
        return Preflight(source, DatabaseSummary("", "", ""), spec.kind, [str(exc)])

    if not source.reachable:
        problems.append(f"The current database can't be read: {source.error}")
    if resolved.url and resolved.url == config.db.url:
        problems.append("That is the database already in use.")

    if resolved.url:
        target = summarize(resolved.url, resolved.docker_managed)
        if resolved.kind == "postgres" and not target.reachable:
            problems.append(f"Couldn't connect: {target.error}")
        if target.reachable and target.rows > 0:
            problems.append(
                f"The destination isn't empty ({target.records:,} records). A move only "
                "goes into an empty or new database, so nothing is overwritten."
            )
    else:
        target = DatabaseSummary(
            resolved.label, "postgresql", "Will be created and started"
        )
    if source.reachable and source.records == 0:
        warnings.append("The current database has no records to move.")
    return Preflight(
        source,
        target,
        resolved.label,
        problems,
        warnings,
        estimate_seconds=max(5, source.rows // ROWS_PER_SECOND),
    )


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@dataclass
class MoveRecord:
    id: str
    started_at: str
    status: Status
    source_label: str
    source_location: str
    target_label: str
    target_location: str
    finished_at: str | None = None
    seconds: float | None = None
    counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    problems: list[str] = field(default_factory=list)
    # What `revert` needs. The URLs can hold a password, so the file is private
    # (see _save) -- config.toml already holds the same.
    from_url: str = ""
    from_docker_managed: bool = False
    to_url: str = ""
    reverted_at: str | None = None


def _history_path(config: Config) -> Path:
    return config.project_root / "_civex" / HISTORY_FILE


def list_moves(config: Config) -> list[MoveRecord]:
    """Past moves, newest first."""
    path = _history_path(config)
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [MoveRecord(**r) for r in reversed(rows)]


def _save(config: Config, record: MoveRecord) -> None:
    path = _history_path(config)
    rows = [asdict(r) for r in reversed(list_moves(config)) if r.id != record.id]
    rows.append(asdict(record))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def public(record: MoveRecord) -> dict:
    """A record safe to send to a browser: no connection URLs."""
    d = asdict(record)
    for key in ("from_url", "to_url"):
        d.pop(key, None)
    return d


# ---------------------------------------------------------------------------
# The move
# ---------------------------------------------------------------------------

ProgressFn = Callable[[engine_move.Progress], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_move(
    config: Config,
    spec: TargetSpec,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    on_start: Callable[[MoveRecord], None] | None = None,
) -> MoveRecord:
    """Move every row to the target, verify, then switch config to it.

    Raises ValidationError for anything the user must fix first (target not
    empty, Docker unavailable...). A failed or cancelled copy raises nothing
    worse: the record comes back with status "failed"/"cancelled", config is
    unchanged, and the source was only ever read."""
    if not _active.acquire(blocking=False):
        raise ValidationError("A database move is already running.")
    try:
        return _run_move(config, spec, progress, cancel, on_start)
    finally:
        _active.release()


def _run_move(
    config: Config,
    spec: TargetSpec,
    progress: ProgressFn | None,
    cancel: threading.Event | None,
    on_start: Callable[[MoveRecord], None] | None,
) -> MoveRecord:
    check = preflight(config, spec)
    if not check.can_proceed:
        raise ValidationError(" ".join(check.problems))

    target = resolve_target(config, spec, provision=True)
    if spec.kind == "docker":
        # Provisioning may have just started a container that already held data.
        again = summarize(target.url, True)
        if again.rows > 0:
            raise ValidationError(
                f"The Docker database already holds {again.records:,} records. "
                "A move only goes into an empty one."
            )

    record = MoveRecord(
        id=uuid.uuid4().hex[:12],
        started_at=_now(),
        status="running",
        source_label=check.source.label,
        source_location=check.source.location,
        target_label=target.label,
        target_location=db_service.redact_url(target.url),
        from_url=config.db.url,
        from_docker_managed=config.db.docker_managed,
        to_url=target.url,
    )
    _save(config, record)
    if on_start:
        on_start(record)

    created_sqlite = (
        Path(urllib.parse.urlparse(target.url).path) if spec.kind == "sqlite" else None
    )
    source = target_engine = None
    try:
        # Both ends at the same schema revision before a single row moves.
        db_service.apply_migrations(config.db.url)
        db_service.apply_migrations(target.url)
        source, target_engine = _engine(config.db.url), _engine(target.url)
        result = engine_move.copy_database(source, target_engine, progress, cancel)
        record.counts, record.seconds = result.counts, round(result.seconds, 1)
        if not result.verified:
            record.status, record.problems = "failed", result.problems
            record.error = (
                "The copy didn't match the original, so nothing was switched."
            )
        else:
            config.db = DBConfig(url=target.url, docker_managed=target.docker_managed)
            save_config(config)
            record.status = "done"
    except engine_move.MoveCancelled:
        record.status, record.error = "cancelled", "Cancelled. Nothing was changed."
    except Exception as exc:
        record.status = "failed"
        record.error = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    finally:
        for engine in (source, target_engine):
            if engine is not None:
                engine.dispose()
        record.finished_at = _now()
        # A new SQLite file we created for a move that didn't finish is just litter.
        if record.status != "done" and created_sqlite is not None:
            created_sqlite.unlink(missing_ok=True)
        _save(config, record)
    return record


# ---------------------------------------------------------------------------
# Revert
# ---------------------------------------------------------------------------


def revert(config: Config, move_id: str) -> MoveRecord:
    """Point config back at the database a move came from. Nothing is copied:
    anything written to the new database since the move stays there."""
    record = next((r for r in list_moves(config) if r.id == move_id), None)
    if record is None:
        raise ValidationError("No such move.")
    if record.status != "done":
        raise ValidationError("Only a completed move can be reverted.")
    if record.reverted_at:
        raise ValidationError("That move was already reverted.")
    if config.db.url != record.to_url:
        raise ValidationError(
            "The project no longer uses the database that move created, so it "
            "can't be reverted from here."
        )
    err = db_service.test_connection(record.from_url)
    if err:
        raise ValidationError(f"The original database can't be reached: {err}")
    config.db = DBConfig(url=record.from_url, docker_managed=record.from_docker_managed)
    save_config(config)
    record.reverted_at = _now()
    _save(config, record)
    return record
