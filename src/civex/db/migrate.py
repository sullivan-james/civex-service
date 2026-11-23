"""Applies Alembic migrations against a live engine.

Replaces the old ad hoc create_all() + raw "ALTER TABLE ... ADD COLUMN"
list that used to live in civex.context. Every install falls into one of
three states the first time it connects after upgrading to this version of
civex:

  - Brand new project: no tables at all. upgrade() creates every table from
    scratch and stamps `alembic_version` at head in the same step.
  - Pre-existing project from before Alembic existed: app tables are
    already present (e.g. `schemas`) but there's no `alembic_version`
    table. Its schema already matches what the baseline migration produces
    -- the old code ran an idempotent ALTER TABLE list on every connection,
    so any such project is already at the shape the baseline migration
    describes. Stamp it at head without replaying anything (replaying
    `create_table` against existing tables would fail).
  - Already migrated: `alembic_version` exists. upgrade() applies whatever
    migrations are newer than its current revision.

ensure_schema_current() is checked once per engine per process (engines are
already cached per DB URL by callers), so it's cheap to call on every
AppContext build without callers needing to reason about which of the three
states a given project is in.
"""

from __future__ import annotations

import functools
import sys
import threading
from contextlib import contextmanager
from typing import Callable, Iterator
import weakref
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from civex.config import DEFAULT_RECORDS_PARTITIONS, PartitionLayout
from civex.db import partitioning
from civex.db.partitioning import ensure_audit_partitions, ensure_audit_partitions_daily

__all__ = [
    "PartitionLayout",
    "RecordsPartitioning",
    "convert_records_partitions",
    "ensure_audit_partitions",
    "ensure_schema_current",
    "ProgressCallback",
    "missing_structure",
    "pending_migrations",
    "records_partitioning",
    "reporting_progress",
    "too_new_error",
]

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Present in every pre-Alembic install; absence means "brand new project".
_LEGACY_MARKER_TABLE = "schemas"

# Weak, so an engine nobody uses any more (a test's, a closed project's) is
# freed with its compiled-statement cache instead of being kept here forever.
_migrated_engines: weakref.WeakSet[Engine] = weakref.WeakSet()
_migrate_lock = threading.Lock()

# (step, total, description): called as each pending migration starts, step
# counting from 1. Step 0 means "waiting for another process that is upgrading
# this project" (total 0).
ProgressCallback = Callable[[int, int, str], None]
_default_progress: ProgressCallback | None = None


@contextmanager
def reporting_progress(progress: ProgressCallback | None) -> Iterator[None]:
    """Report migrations that start inside the block to `progress`, for callers
    (the CLI) that reach `ensure_schema_current` through other code."""
    global _default_progress
    previous, _default_progress = _default_progress, progress
    try:
        yield
    finally:
        _default_progress = previous


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return cfg


def ensure_schema_current(
    engine: Engine,
    layout: PartitionLayout | None = None,
    *,
    progress: ProgressCallback | None = None,
) -> None:
    """Create or upgrade the schema at `engine` to the latest revision.

    No-op after the first call for a given engine instance.

    `layout` chooses the PostgreSQL table layout (`records` hash partitions,
    monthly `audit_log`) a database gets when it runs the migration that
    partitions them; default `PartitionLayout.from_env()`. It has no effect on
    a database that already ran that migration, or on SQLite.

    `progress(step, total, description)`, if given, is called as each pending
    migration starts (nothing is called when there is nothing to do), so a
    caller can tell the user a long upgrade is under way. See
    `pending_migrations` to ask first.
    """
    progress = progress or _default_progress
    if engine in _migrated_engines:
        return

    # Alembic's `context`/`op` proxies are module globals, so two threads
    # migrating at once corrupt each other (KeyError: 'script'). The server
    # builds a context per request in a threadpool, and the UI fires a burst
    # of requests on load -- all of which see an un-migrated engine until the
    # first one finishes. Serialise, and re-check once the lock is held.
    with _migrate_lock:
        if engine in _migrated_engines:
            return
        with engine.connect() as connection:
            with _cross_process_lock(connection, progress):
                _migrate_connection(connection, layout, progress)
        _migrated_engines.add(engine)
    # Months of `audit_log` partitions ahead of now: a no-op unless this is a
    # partitioned PostgreSQL database that has run out. Best effort.
    ensure_audit_partitions_daily(
        engine, (layout or PartitionLayout.from_env()).audit_months_ahead
    )


@contextmanager
def _cross_process_lock(
    connection: Connection, progress: ProgressCallback | None = None
) -> Iterator[None]:
    """On PostgreSQL, one process at a time migrates a given schema: two
    workers opening a new or old repository together would otherwise both try
    to create `alembic_version` (or both convert `records`). The in-process
    lock above does not cover other processes."""
    if connection.dialect.name == "sqlite":
        with _sqlite_file_lock(connection, progress):
            yield
        return
    if connection.dialect.name != "postgresql":
        yield
        return
    key = "SELECT hashtextextended(current_database() || '/' || current_schema() || '/civex-migrate', 0)"
    lock_key = key.removeprefix("SELECT ")
    if (
        progress is not None
        and not connection.execute(
            text(f"SELECT pg_try_advisory_lock({lock_key})")
        ).scalar()
    ):
        connection.commit()
        progress(0, 0, _WAITING)
        connection.execute(text(f"SELECT pg_advisory_lock({lock_key})"))
    elif progress is None:
        connection.execute(text(f"SELECT pg_advisory_lock({lock_key})"))
    connection.commit()
    try:
        yield
    finally:
        connection.rollback()
        connection.execute(
            text(f"SELECT pg_advisory_unlock({key.removeprefix('SELECT ')})")
        )
        connection.commit()


_WAITING = (
    "Another civex process is upgrading this project; waiting for it to finish..."
)


@contextmanager
def _sqlite_file_lock(
    connection: Connection, progress: ProgressCallback | None
) -> Iterator[None]:
    """SQLite has no advisory lock, so two processes (two desktop windows, a
    CLI beside a server) could migrate one file at once. Hold an OS file lock
    on a sidecar file instead; it is released if the process dies. A database
    that is in memory, or a folder we cannot write to, is not locked."""
    database = connection.engine.url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        yield
        return
    # Only an upgrade needs the lock; opening a current project leaves no file.
    if not _pending(connection):
        yield
        return
    try:
        handle = open(database + ".migrate-lock", "a+b")
    except OSError:
        yield
        return
    try:
        if not _try_lock(handle):
            if progress is not None:
                progress(0, 0, _WAITING)
            _lock_blocking(handle)
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()


if sys.platform == "win32":
    import msvcrt

    def _try_lock(handle) -> bool:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _lock_blocking(handle) -> None:
        import time

        while not _try_lock(handle):
            time.sleep(0.2)

    def _unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(handle) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _lock_blocking(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def missing_structure(engine: Engine) -> list[str]:
    """Tables and columns this civex's models expect that the database at
    `engine` lacks ("views.files_layout"), whatever revision it is stamped
    at: a database stamped current but missing a migration's work (a
    migration reordered after it ran) looks current to Alembic and fails
    only when the missing part is used."""
    from civex.db.models import Base

    found = inspect(engine)
    have = set(found.get_table_names())
    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in have:
            missing.append(table.name)
            continue
        columns = {c["name"] for c in found.get_columns(table.name)}
        missing += [
            f"{table.name}.{c.name}" for c in table.columns if c.name not in columns
        ]
    return missing


@functools.lru_cache(maxsize=1)
def _script_directory() -> ScriptDirectory:
    # Parsing the migration files is the costly part of knowing head, and they
    # don't change while the process runs, so it is done once.
    return ScriptDirectory(str(_MIGRATIONS_DIR))


def head_revision() -> str:
    """The revision this civex migrates a database to."""
    head = _script_directory().get_current_head()
    assert head is not None
    return head


def _unknown_revisions(revisions: list[str]) -> list[str]:
    """The `revisions` this civex has no migration for (a newer civex's)."""
    from alembic.util.exc import CommandError

    script = _script_directory()
    unknown: list[str] = []
    for revision in revisions:
        try:
            script.get_revision(revision)
        except (CommandError, KeyError):
            unknown.append(revision)
    return unknown


def _pending(connection: Connection) -> list[tuple[str, str]]:
    from alembic.runtime.migration import MigrationContext

    if not inspect(connection).has_table("alembic_version"):
        return []
    current = list(MigrationContext.configure(connection).get_current_heads())
    connection.rollback()
    if not current or _unknown_revisions(current):
        return []
    script = _script_directory()
    steps = script.iterate_revisions("head", tuple(current))
    return [
        (rev.revision, (rev.doc or rev.revision).strip().splitlines()[0].strip())
        for rev in reversed(list(steps))
        if rev.revision not in current
    ]


def pending_migrations(engine: Engine) -> list[tuple[str, str]]:
    """The migrations `ensure_schema_current` would run on the database at
    `engine`, oldest first, as (revision, one-line description). Cheap, and
    changes nothing. Empty for a new database or one made before Alembic
    (those are created or stamped, not upgraded, so are quick) and for a
    database from a newer civex."""
    with engine.connect() as connection:
        return _pending(connection)


@dataclass(frozen=True)
class SchemaStatus:
    """Where a database stands against this civex, from `schema_status`.

    `current` is the stamped revision (several joined by ", " if it is stamped
    at more than one), None when it has none. `behind` means a migration
    would run (not stamped, or stamped older than `head`); `too_new` means it
    is stamped by a newer civex (`behind` is then False: nothing here can
    migrate it). `missing_structure` is None unless asked for.
    """

    current: str | None
    head: str
    behind: bool
    too_new: bool
    missing_structure: tuple[str, ...] | None = None

    @property
    def up_to_date(self) -> bool:
        return not self.behind and not self.too_new


def schema_status(engine: Engine, *, check_structure: bool = False) -> SchemaStatus:
    """Report the database at `engine` against this civex, changing nothing.

    Unlike `ensure_schema_current` it never migrates, stamps, creates a table
    or takes the migration lock, so a host can ask "is this tenant current?"
    for a fleet (or to refuse a stale one) without paying for a migration
    attempt. It uses one connection and, normally, one read of
    `alembic_version`; head is computed once per process. Whatever the
    connection's default schema is (a PostgreSQL `search_path` set in the
    URL's `options`) is the one examined.

    A database with civex's tables but no `alembic_version` (from before
    Alembic) reports `current=None, behind=True`: `ensure_schema_current`
    would stamp it. `check_structure=True` also reflects the tables
    (`missing_structure`), which is much slower, for a doctor-style check.
    """
    head = head_revision()
    with engine.connect() as connection:
        revisions: list[str] = []
        if inspect(connection).has_table("alembic_version"):
            revisions = [
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                )
            ]
        connection.rollback()
    missing = tuple(missing_structure(engine)) if check_structure else None
    too_new = bool(_unknown_revisions(revisions))
    return SchemaStatus(
        current=", ".join(sorted(revisions)) or None,
        head=head,
        behind=not too_new and revisions != [head],
        too_new=too_new,
        missing_structure=missing,
    )


@dataclass(frozen=True)
class RecordsPartitioning:
    """How `records` is laid out. `partitions` is 0 for a plain table (or no
    table); `supported` is False off PostgreSQL, where it never partitions."""

    supported: bool
    partitioned: bool
    partitions: int


def records_partitioning(engine: Engine) -> RecordsPartitioning:
    """Report how `records` is laid out at `engine` (honouring a `search_path`
    on it), changing nothing."""
    with engine.connect() as connection:
        try:
            if connection.dialect.name != "postgresql":
                return RecordsPartitioning(False, False, 0)
            if not partitioning.is_partitioned(connection, "records"):
                return RecordsPartitioning(True, False, 0)
            return RecordsPartitioning(
                True, True, len(partitioning.partitions_of(connection, "records"))
            )
        finally:
            connection.rollback()


def convert_records_partitions(
    engine: Engine, partitions: int = DEFAULT_RECORDS_PARTITIONS
) -> RecordsPartitioning:
    """Lay an existing PostgreSQL `records` table out as `partitions` hash
    partitions on `id`, and report the result (`records_partitioning`).

    For a database created with partitioning off (or before it existed) that a
    host now wants partitioned. A no-op, returning the current state, when
    `partitions` < 2, the table is already partitioned (at any count), or the
    database is not PostgreSQL. A populated table is copied once: writers wait
    (about 50 s per million records; `docs/contributing/records-partitioning.md`).
    One process at a time per schema (the migration's advisory lock). Raises
    `ValueError` when there is no `records` table yet: migrate
    (`ensure_schema_current`) first.
    """
    with engine.connect() as connection:
        if connection.dialect.name == "postgresql" and not inspect(
            connection
        ).has_table("records"):
            connection.rollback()
            raise ValueError(
                "`records` does not exist: run ensure_schema_current first"
            )
        connection.rollback()
        with _cross_process_lock(connection):
            try:
                if partitioning.partition_records(connection, partitions):
                    connection.commit()
            except BaseException:
                connection.rollback()
                raise
    return records_partitioning(engine)


def too_new_error(database: str, revisions: list[str]) -> Exception:
    """The error for a database at `revisions` this civex doesn't know.

    The one place its wording is made, shared by the migration check and the
    `civex serve` pre-flight."""
    from civex import __version__
    from civex.domain.exceptions import DatabaseTooNewError

    return DatabaseTooNewError(
        f"This project's database ({database}) was last used by a newer version "
        f"of civex: it is at revision {', '.join(revisions)}, which civex "
        f"{__version__} doesn't know. Update civex with `civex update`, then "
        "try again. Your data hasn't been changed.",
        database=database,
        revisions=revisions,
        civex_version=__version__,
        known_head=head_revision(),
    )


def _refuse_newer_database(connection: Connection) -> None:
    """Say so plainly when the database is from a newer civex.

    Alembic's own error for this ("Can't locate revision identified by ...")
    reads as if the database were corrupt. The usual cause is a project last
    opened by a newer civex than the one running now, e.g. a second install
    that was updated and this one wasn't.
    """
    from alembic.runtime.migration import MigrationContext

    unknown = _unknown_revisions(
        list(MigrationContext.configure(connection).get_current_heads())
    )
    if not unknown:
        return
    where = connection.engine.url.render_as_string(hide_password=True)
    raise too_new_error(where, unknown)


def _migrate_connection(
    connection: Connection,
    layout: PartitionLayout | None = None,
    progress: ProgressCallback | None = None,
) -> None:
    cfg = _alembic_config()
    cfg.attributes["connection"] = connection
    cfg.attributes["layout"] = layout

    # Reflecting table names below implicitly opens a transaction on this
    # connection. Alembic then detects that active transaction and treats it
    # as caller-owned (won't commit it itself) -- so we must commit here.
    tables = inspect(connection).get_table_names()
    if "alembic_version" not in tables and _LEGACY_MARKER_TABLE in tables:
        command.stamp(cfg, "head")
    else:
        _refuse_newer_database(connection)
        pending = _pending(connection)
        if pending and progress is not None:
            total = len(pending)
            done = 0
            progress(1, total, pending[0][1])

            def on_applied(revision: str) -> None:
                nonlocal done
                done += 1
                if done < total:
                    progress(done + 1, total, pending[done][1])

            cfg.attributes["on_applied"] = on_applied
        command.upgrade(cfg, "head")
    connection.commit()

    if connection.dialect.name == "sqlite":
        # Migrations run with PRAGMA foreign_keys=OFF while any table rebuild
        # is in progress (see migrations/env.py). PRAGMA foreign_keys can't
        # be changed while a transaction is open, and one is reliably open
        # again by the time command.upgrade() returns (e.g. batch mode's
        # INSERT...SELECT copy step) -- so this has to happen after the
        # commit above, not inside env.py.
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
