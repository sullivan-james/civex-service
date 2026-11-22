"""Managed field indexes and planner statistics for this computer's database.

Every step is committed by itself, so call it with nothing pending (the CLI's
upkeep and the server's `index_jobs` do). On SQLite a step runs on the
session's own connection and is committed at once, one index per transaction,
so the write lock is held for one build at a time, and a build gives way to
saves (`db/index_gate.py`: `create` then raises `IndexBuildYielded`). On
PostgreSQL an index is built and dropped CONCURRENTLY, which can't
run inside a transaction, so it uses a connection of its own in autocommit;
the session's transaction is committed first (a CONCURRENTLY build waits for
every transaction holding a lock on records, its caller's included), so call
it with nothing pending (the CLI and the server's `index_jobs` do).
"""

from __future__ import annotations

from typing import cast

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext

from sqlalchemy.exc import OperationalError

from civex.db import field_indexes, index_gate, statistics
from civex.domain.field_index import INDEX_BUILT, FieldIndexSpec, IndexBuildYielded


class LocalFieldIndexRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    @property
    def _pg(self) -> bool:
        return self._s.get_bind().dialect.name == "postgresql"

    @property
    def _sqlite_file(self) -> str | None:
        if self._pg:
            return None
        return index_gate.sqlite_file(cast(Engine, self._s.get_bind()).url.database)

    def _nothing_pending(self) -> None:
        if self._s.new or self._s.dirty or self._s.deleted:
            raise RuntimeError("Commit before changing indexes: changes are pending")

    def _sqlite_step(self, step) -> None:
        """Run one change on the session's connection, giving way to saves,
        and commit it."""
        self._nothing_pending()
        conn = self._s.connection()
        db = self._sqlite_file
        try:
            with index_gate.yielding(conn, db) if db else nullcontext():
                step(conn)
        except OperationalError as e:
            self._s.rollback()
            if index_gate.is_interrupt(e):
                raise IndexBuildYielded() from e
            raise
        self._s.commit()

    @contextmanager
    def upkeep(self) -> Iterator[None]:
        db = self._sqlite_file
        with index_gate.upkeep(db) if db else nullcontext():
            yield

    def quiet_for(self) -> float:
        db = self._sqlite_file
        return index_gate.quiet_for(db) if db else float("inf")

    def _autocommit(self) -> Connection:
        # A CONCURRENTLY build or drop waits for every transaction that holds
        # a lock on records, this session's own included (any read takes
        # one), and this thread would wait on itself for ever: end it first.
        self._nothing_pending()
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
            self._sqlite_step(lambda conn: field_indexes.create(conn, spec))

    def drop(self, name: str) -> None:
        if self._pg:
            with self._autocommit() as conn:
                field_indexes.drop(conn, name)
        else:
            self._sqlite_step(lambda conn: field_indexes.drop(conn, name))

    def refresh_statistics(self, reason: str) -> None:
        if self._pg:
            with self._autocommit() as conn:
                statistics.refresh(conn, reason)
        else:
            statistics.refresh(self._s.connection(), reason)
            if reason == INDEX_BUILT:  # the end of an upkeep, which commits as it goes
                self._s.commit()
