"""Managed field indexes and planner statistics for this computer's database.

On SQLite the work runs on the session's own connection, inside its
transaction (DDL and ANALYZE are transactional there, and a second connection
would wait on the session's own write lock): the caller commits, as for any
write. On PostgreSQL an index is built and dropped CONCURRENTLY, which can't
run inside a transaction, so it uses a connection of its own in autocommit;
the session's transaction is committed first (a CONCURRENTLY build waits for
every transaction holding a lock on records, its caller's included), so call
it with nothing pending (the CLI and the server's `index_jobs` do).
"""

from __future__ import annotations

from typing import cast

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from civex.db import field_indexes, statistics
from civex.domain.field_index import FieldIndexSpec


class LocalFieldIndexRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    @property
    def _pg(self) -> bool:
        return self._s.get_bind().dialect.name == "postgresql"

    def _autocommit(self) -> Connection:
        # A CONCURRENTLY build or drop waits for every transaction that holds
        # a lock on records, this session's own included (any read takes
        # one), and this thread would wait on itself for ever: end it first.
        if self._s.new or self._s.dirty or self._s.deleted:
            raise RuntimeError("Commit before changing indexes: changes are pending")
        self._s.commit()
        engine = cast(Engine, self._s.get_bind())
        return engine.connect().execution_options(isolation_level="AUTOCOMMIT")

    def existing(self) -> set[str]:
        return field_indexes.existing(self._s.connection())

    def create(self, spec: FieldIndexSpec) -> None:
        if self._pg:
            with self._autocommit() as conn:
                field_indexes.create(conn, spec)
        else:
            field_indexes.create(self._s.connection(), spec)

    def drop(self, name: str) -> None:
        if self._pg:
            with self._autocommit() as conn:
                field_indexes.drop(conn, name)
        else:
            field_indexes.drop(self._s.connection(), name)

    def refresh_statistics(self, reason: str) -> None:
        if self._pg:
            with self._autocommit() as conn:
                statistics.refresh(conn, reason)
        else:
            statistics.refresh(self._s.connection(), reason)
