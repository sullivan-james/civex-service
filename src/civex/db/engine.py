"""Shared engine-creation helper.

SQLite ignores FOREIGN KEY constraints unless `PRAGMA foreign_keys=ON` is set
on every connection -- without this, the composite FK enforcing
parent_record_id/dataset_id consistency (CIVEX-168) silently does nothing on
SQLite and only actually protects PostgreSQL installs.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine


def enable_sqlite_foreign_keys(engine: Engine) -> Engine:
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine
