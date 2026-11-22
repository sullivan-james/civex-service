"""Shared engine-creation helper.

SQLite ignores FOREIGN KEY constraints unless `PRAGMA foreign_keys=ON` is set
on every connection -- without this, the composite FK enforcing
parent_record_id/dataset_id consistency (CIVEX-168) silently does nothing on
SQLite and only actually protects PostgreSQL installs.

Each connection also waits up to SQLITE_BUSY_TIMEOUT_MS for a competing writer
(a transfer saving progress, an upload, the CLI in another process) rather than
the driver's 5 seconds. WAL would help more but is deliberately not used: it
adds `-wal`/`-shm` files that break copying or moving the database file, and it
is unreliable on network and WSL-mounted drives.

As a connection closes it refreshes the planner's statistics
(`db/statistics.py`, which decides when that happens).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from civex.db import index_gate
from civex.db.statistics import sqlite_optimize


SQLITE_BUSY_TIMEOUT_MS = 30_000


def enable_sqlite_foreign_keys(engine: Engine, optimize: bool = True) -> Engine:
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cursor.close()

        db = index_gate.sqlite_file(engine.url.database)
        if db is not None:

            @event.listens_for(engine, "before_cursor_execute")
            def _give_writes_their_turn(
                conn: Any, cursor: Any, statement: str, *args: Any
            ) -> None:
                # A save asks a running index build to give way (index_gate).
                if not conn.info.get(index_gate.BUILDER):
                    index_gate.note_write(db, statement)

        if not optimize:  # a database that is only being read (a move's source)
            return engine

        @event.listens_for(engine, "close")
        def _optimize_on_close(dbapi_connection: Any, connection_record: Any) -> None:
            # SQLite's advice: refresh the planner's statistics as a connection
            # closes (cheap: only what changed enough, a sample of rows). Never
            # wait for another writer to do it.
            try:
                dbapi_connection.execute("PRAGMA busy_timeout=0")
            except Exception:  # noqa: BLE001 - already unusable: nothing to do
                return
            sqlite_optimize(dbapi_connection)

    return engine
