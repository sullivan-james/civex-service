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


def _run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        # SQLite can't ALTER most things in place; batch mode recreates the
        # table under the hood instead. No-op cost on other dialects.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
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
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=connection.dialect.name == "sqlite",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations (--sql) are not supported for civex.")

_run_migrations_online()
