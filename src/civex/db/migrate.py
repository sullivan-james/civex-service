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

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Present in every pre-Alembic install; absence means "brand new project".
_LEGACY_MARKER_TABLE = "schemas"

_migrated_engines: set[Engine] = set()


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return cfg


def ensure_schema_current(engine: Engine) -> None:
    """Create or upgrade the schema at `engine` to the latest revision.

    No-op after the first call for a given engine instance.
    """
    if engine in _migrated_engines:
        return

    with engine.connect() as connection:
        _migrate_connection(connection)

    _migrated_engines.add(engine)


def _migrate_connection(connection: Connection) -> None:
    cfg = _alembic_config()
    cfg.attributes["connection"] = connection

    # Reflecting table names below implicitly opens a transaction on this
    # connection. Alembic then detects that active transaction and treats it
    # as caller-owned (won't commit it itself) -- so we must commit here.
    tables = inspect(connection).get_table_names()
    if "alembic_version" not in tables and _LEGACY_MARKER_TABLE in tables:
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")
    connection.commit()
