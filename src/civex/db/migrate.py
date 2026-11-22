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
import threading
from contextlib import contextmanager
from typing import Iterator
import weakref
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from civex.config import PartitionLayout
from civex.db.partitioning import ensure_audit_partitions, ensure_audit_partitions_daily

__all__ = [
    "PartitionLayout",
    "ensure_audit_partitions",
    "ensure_schema_current",
    "missing_structure",
    "too_new_error",
]

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Present in every pre-Alembic install; absence means "brand new project".
_LEGACY_MARKER_TABLE = "schemas"

# Weak, so an engine nobody uses any more (a test's, a closed project's) is
# freed with its compiled-statement cache instead of being kept here forever.
_migrated_engines: weakref.WeakSet[Engine] = weakref.WeakSet()
_migrate_lock = threading.Lock()


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return cfg


def ensure_schema_current(
    engine: Engine, layout: PartitionLayout | None = None
) -> None:
    """Create or upgrade the schema at `engine` to the latest revision.

    No-op after the first call for a given engine instance.

    `layout` chooses the PostgreSQL table layout (`records` hash partitions,
    monthly `audit_log`) a database gets when it runs the migration that
    partitions them; default `PartitionLayout.from_env()`. It has no effect on
    a database that already ran that migration, or on SQLite.
    """
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
            with _cross_process_lock(connection):
                _migrate_connection(connection, layout)
        _migrated_engines.add(engine)
    # Months of `audit_log` partitions ahead of now: a no-op unless this is a
    # partitioned PostgreSQL database that has run out. Best effort.
    ensure_audit_partitions_daily(
        engine, (layout or PartitionLayout.from_env()).audit_months_ahead
    )


@contextmanager
def _cross_process_lock(connection: Connection) -> Iterator[None]:
    """On PostgreSQL, one process at a time migrates a given schema: two
    workers opening a new or old repository together would otherwise both try
    to create `alembic_version` (or both convert `records`). The in-process
    lock above does not cover other processes."""
    if connection.dialect.name != "postgresql":
        yield
        return
    key = "SELECT hashtextextended(current_database() || '/' || current_schema() || '/civex-migrate', 0)"
    connection.execute(text(f"SELECT pg_advisory_lock({key.removeprefix('SELECT ')})"))
    connection.commit()
    try:
        yield
    finally:
        connection.rollback()
        connection.execute(
            text(f"SELECT pg_advisory_unlock({key.removeprefix('SELECT ')})")
        )
        connection.commit()


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
    connection: Connection, layout: PartitionLayout | None = None
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
