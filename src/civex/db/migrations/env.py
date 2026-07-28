"""Alembic environment for civex.

Runs in two modes:

  1. Embedded (normal path) — civex.db.migrate passes a live Connection via
     `config.attributes["connection"]` so migrations run inside the same
     engine/transaction the caller already opened. No separate DB URL needed.
  2. Standalone — `alembic -x db_url=<url> upgrade head` from a shell, for
     manual inspection/debugging. Opens its own engine against `db_url`.

Offline mode (`alembic upgrade head --sql`) is not supported: civex targets
SQLite and PostgreSQL interactively, not generated SQL scripts for DBAs.
"""

from __future__ import annotations

from alembic import context

from civex.db.models import Base

config = context.config
target_metadata = Base.metadata


def _configure_and_run(connection) -> None:
    is_sqlite = connection.dialect.name == "sqlite"
    if is_sqlite:
        # Batch mode's table-recreation trick needs FK enforcement off during
        # the rebuild -- this is SQLite's own documented ALTER TABLE
        # procedure (disable FK enforcement, rebuild, re-enable) --
        # otherwise self-referential FKs like records' composite
        # parent/dataset constraint raise "foreign key mismatch" mid-rebuild.
        # Issued via the raw DBAPI cursor rather than connection.exec_driver_
        # sql: going through Core would autobegin a transaction that Core
        # treats as pre-existing once alembic's own context.begin_transaction()
        # starts below, which makes alembic skip committing it (it assumes
        # a pre-existing transaction is caller-owned -- see the same caveat
        # in civex.db.migrate's reflection call).
        # Re-enabling the pragma is civex.db.migrate's job: by the time this
        # function returns, a real DML-triggered transaction is typically
        # open (e.g. the INSERT...SELECT batch mode uses to copy rows into
        # the rebuilt table), so a PRAGMA here would silently no-op.
        raw_cursor = connection.connection.dbapi_connection.cursor()
        raw_cursor.execute("PRAGMA foreign_keys=OFF")
        raw_cursor.close()
    # SQLite can't ALTER most things in place; batch mode recreates the
    # table under the hood instead. No-op cost on other dialects.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=is_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure_and_run(connection)
        return

    db_url = context.get_x_argument(as_dictionary=True).get(
        "db_url"
    ) or config.get_main_option("sqlalchemy.url")
    if not db_url:
        raise RuntimeError(
            "No connection passed and no -x db_url=<url> given. "
            "Standalone use: alembic -x db_url=sqlite:///path/to/civex.db upgrade head"
        )
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            _configure_and_run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations (--sql) are not supported for civex.")

_run_migrations_online()
