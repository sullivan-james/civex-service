"""How much a project holds, cheaply: the numbers a host needs to meter it.

`project_usage(engine)` is a stable, public function for a host that runs many
projects (one engine each, or one engine whose `search_path` picks the
project's schema) and bills or limits by stored bytes and record count. It
reads civex's own bookkeeping so the host does not have to know the tables.

Cost is bounded whatever the size of the project:

- PostgreSQL: records come from the planner (`pg_class.reltuples`), which
  scans nothing. A table never analysed (`reltuples <= 0`) falls back to a
  count capped at `RECORDS_COUNT_CAP`. Every statement runs under
  `statement_timeout` in a read-only transaction, and a figure that cannot be
  had in time is `None`, not an error.
- SQLite: counts are exact (`records_exact` is True); the project is one local
  file, so a count is cheap enough.

Bytes are the sum over distinct files: a blob stored on several drives, or
referenced by several records, counts once (its largest recorded copy), the
way `civex.repositories.local.inventory.stored_files` counts it. Read-only, so
safe on a read replica.

The bytes figure reads the `stored_objects` inventory, one pass over it, so
its cost grows with the number of files; the statement timeout is what bounds
it (a project too big to total in time reports None). Records on PostgreSQL
are as fresh as the last ANALYZE (a table emptied since can read high). Table
names resolve through the engine's `search_path`, so give a tenant engine a
path that names only that tenant's schema.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeVar

from sqlalchemy import func, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

_log = logging.getLogger(__name__)

__all__ = ["RECORDS_COUNT_CAP", "STATEMENT_TIMEOUT_MS", "Usage", "project_usage"]

# A never-analysed table is counted up to this many rows, then reported as
# "at least this many" (records_exact stays False).
RECORDS_COUNT_CAP = 100_000
# Per-statement ceiling on PostgreSQL.
STATEMENT_TIMEOUT_MS = 5_000

_T = TypeVar("_T")


@dataclass(frozen=True)
class Usage:
    """What a project holds. A `None` figure could not be measured (table
    missing, statement timed out); it is never a guess of zero.

    `stored_bytes`/`stored_objects`: distinct files in the object store (see
    module docstring). `records_estimate`: records, including soft-deleted
    ones the database still holds; `records_exact` says whether it is a count
    (True) or a planner estimate / capped count (False)."""

    stored_bytes: int | None
    stored_objects: int | None
    records_estimate: int | None
    records_exact: bool
    measured_at: datetime


def project_usage(engine: Engine, schema: str | None = None) -> Usage:
    """Measure the project behind `engine`, honouring its `search_path`.

    A host sharing one engine across many tenants may pass `schema` instead:
    the measurement then runs with `search_path` set to that PostgreSQL schema
    for its own transaction (ignored on SQLite, which has none)."""
    pg = engine.dialect.name == "postgresql"
    stored = _attempt(engine, pg, schema, _stored)
    records = _attempt(engine, pg, schema, _records_pg if pg else _records_exact)
    return Usage(
        stored_bytes=stored[0] if stored else None,
        stored_objects=stored[1] if stored else None,
        records_estimate=records[0] if records else None,
        records_exact=bool(records and records[1]),
        measured_at=datetime.now(timezone.utc),
    )


def _attempt(
    engine: Engine, pg: bool, schema: str | None, fn: Callable[[Connection], _T]
) -> _T | None:
    """Run `fn(conn)` in its own read-only transaction; None on failure, so a
    timeout in one measurement leaves the other intact."""
    try:
        with engine.connect() as conn:
            if pg:
                # A host's engine may be autocommit; SET LOCAL needs a real
                # transaction.
                conn = conn.execution_options(isolation_level="READ COMMITTED")
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(
                    text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
                )
                if schema:
                    quoted = engine.dialect.identifier_preparer.quote_schema(schema)
                    conn.execute(text(f"SET LOCAL search_path = {quoted}"))
            result = fn(conn)
            conn.rollback()
            return result
    except SQLAlchemyError as e:
        _log.warning("usage measurement failed: %s", type(e).__name__, exc_info=True)
        return None


def _stored(conn: Connection) -> tuple[int, int]:
    from civex.db.models import StoredObject

    per_file = (
        select(func.max(StoredObject.size).label("size"))
        .group_by(StoredObject.sha256)
        .subquery()
    )
    row = conn.execute(
        select(func.coalesce(func.sum(per_file.c.size), 0), func.count())
    ).one()
    return int(row[0]), int(row[1])


def _records_exact(conn: Connection) -> tuple[int, bool]:
    from civex.db.models import Record

    return int(
        conn.execute(select(func.count()).select_from(Record)).scalar_one()
    ), True


def _records_pg(conn: Connection) -> tuple[int, bool]:
    tuples = conn.execute(
        text(
            "SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass('records')"
        )
    ).scalar()
    if tuples is not None and tuples > 0:
        return int(tuples), False
    from civex.db.models import Record

    capped = int(
        conn.execute(
            select(func.count()).select_from(
                select(Record.id).limit(RECORDS_COUNT_CAP + 1).subquery()
            )
        ).scalar_one()
    )
    if capped > RECORDS_COUNT_CAP:
        return RECORDS_COUNT_CAP, False
    return capped, True
