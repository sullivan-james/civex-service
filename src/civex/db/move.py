"""Copy every row of one civex database into another.

Backend-agnostic: it takes two SQLAlchemy engines and knows nothing about which
kind each is, so SQLite -> PostgreSQL, PostgreSQL -> SQLite and PostgreSQL ->
PostgreSQL are the same code. SQLAlchemy's own column types do the conversion
(UUID, JSON/JSONB, timezone-aware datetimes), reading through one dialect and
writing through the other.

The copy is atomic: every row goes into the target in one transaction, so a
failure or a cancel leaves the target exactly as it was -- empty. The source is
only ever read. Afterwards the copy is verified against the source before the
caller is told it worked.

Both databases must already be migrated to the same schema revision (the
caller's job -- see civex.services.db_move_service).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import Table, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine

from civex.db.models import Base

# Columns that are derived rather than stored: `records.search_vector` exists
# only on PostgreSQL, where a trigger recomputes it from `data` on every insert.
SKIP_COLUMNS = {"search_vector"}

# Memory bounds. Rows are read a small chunk at a time and written in batches
# capped by both row count and (estimated) bytes, so memory stays flat however
# large the database is, and however large its individual rows are.
BATCH = 2000  # most rows per INSERT
READ_CHUNK = 200  # rows pulled from the source cursor at once
MAX_BATCH_BYTES = 16 * 1024 * 1024  # most data held per INSERT

# Records compared field-by-field after the copy, on top of the row counts.
VERIFY_SAMPLE = 100


class MoveCancelled(Exception):
    """Raised inside a copy when the caller's cancel event is set."""


@dataclass
class Progress:
    """Where a copy is, for a progress bar or a poll."""

    phase: str  # "copy" | "verify" | "finalize"
    table: str | None = None
    rows_done: int = 0
    rows_total: int = 0
    tables_done: int = 0
    tables_total: int = 0
    message: str = ""


@dataclass
class CopyResult:
    counts: dict[str, int] = field(default_factory=dict)  # rows copied per table
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)  # why verification failed

    @property
    def verified(self) -> bool:
        return not self.problems


ProgressFn = Callable[[Progress], None]


def app_tables(engine: Engine) -> list[Table]:
    """Civex's tables that exist in this database, parents before children."""
    present = set(inspect(engine).get_table_names())
    return [t for t in Base.metadata.sorted_tables if t.name in present]


def row_counts(engine: Engine) -> dict[str, int]:
    """Rows per table (zero-row tables included)."""
    with engine.connect() as conn:
        return {
            t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
            for t in app_tables(engine)
        }


def is_empty(engine: Engine) -> bool:
    """No rows in any civex table. A database whose tables exist but hold
    nothing (a freshly migrated one) is empty; a database with no tables at
    all is too."""
    return sum(row_counts(engine).values()) == 0


def _columns(table: Table) -> list[Any]:
    return [c for c in table.columns if c.name not in SKIP_COLUMNS]


def _schema_depths(conn: Connection) -> dict[Any, int]:
    """Schema id -> how many parents it has. Inserting shallow schemas first
    means a parent schema (and, below, a parent record) always exists before
    its child, on every backend, without disabling any constraint."""
    schemas = Base.metadata.tables["schemas"]
    parent = {
        row.id: row.parent_id
        for row in conn.execute(select(schemas.c.id, schemas.c.parent_id))
    }

    def depth(sid: Any) -> int:
        d, seen = 0, set()
        while parent.get(sid) is not None and sid not in seen:
            seen.add(sid)
            sid = parent[sid]
            d += 1
        return d

    return {sid: depth(sid) for sid in parent}


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise MoveCancelled()


def _stream(conn: Connection, stmt: Any):
    """Rows of `stmt` in small chunks, off a server-side cursor where the
    driver has one -- never the whole result set in memory."""
    result = conn.execution_options(stream_results=True).execute(stmt)
    try:
        yield from result.partitions(READ_CHUNK)
    finally:
        result.close()


def _row_bytes(row: Any) -> int:
    """A cheap upper-ish estimate of how much memory a row holds -- exact
    enough to cap a batch; the JSON columns are what can be large."""
    total = 0
    for value in row:
        if isinstance(value, (str, bytes)):
            total += len(value)
        elif isinstance(value, (dict, list)):
            total += len(json.dumps(value, default=str))
        else:
            total += 32
    return total


class _Batcher:
    """Buffers rows for one table and INSERTs them when the buffer reaches
    `max_rows` or `max_bytes`, whichever comes first."""

    def __init__(
        self,
        dst: Connection,
        table: Table,
        names: list[str],
        max_rows: int,
        on_rows: Callable[[int], None],
        max_bytes: int = MAX_BATCH_BYTES,
    ) -> None:
        self._dst, self._table, self._names = dst, table, names
        self._max_rows, self._max_bytes, self._on_rows = max_rows, max_bytes, on_rows
        self._rows: list[Any] = []
        self._bytes = 0

    def add(self, rows: list[Any]) -> None:
        for row in rows:
            self._rows.append(row)
            self._bytes += _row_bytes(row)
            if len(self._rows) >= self._max_rows or self._bytes >= self._max_bytes:
                self.flush()

    def flush(self) -> None:
        if not self._rows:
            return
        n = len(self._rows)
        self._dst.execute(
            self._table.insert(), [dict(zip(self._names, r)) for r in self._rows]
        )
        self._rows, self._bytes = [], 0
        self._on_rows(n)


def _copy_table(
    src: Connection,
    dst: Connection,
    table: Table,
    depths: dict[Any, int],
    batch: int,
    on_rows: Callable[[int], None],
    cancel: threading.Event | None,
) -> None:
    cols = _columns(table)
    names = [c.name for c in cols]
    out = _Batcher(dst, table, names, batch, on_rows)

    if table.name == "schemas":
        # Few rows; order by depth so a parent schema precedes its children.
        rows = sorted(
            src.execute(select(*cols)).all(), key=lambda r: depths.get(r.id, 0)
        )
        _check(cancel)
        out.add(rows)
    elif table.name == "records":
        # A record's parent lives in its schema's parent schema, so copying
        # one schema at a time, shallowest first, always inserts parents first.
        for sid in sorted(depths, key=lambda sid: depths[sid]):
            for rows in _stream(src, select(*cols).where(table.c.schema_id == sid)):
                _check(cancel)
                out.add(rows)
    else:
        for rows in _stream(src, select(*cols)):
            _check(cancel)
            out.add(rows)
    out.flush()


def _sample_problems(src: Engine, dst: Engine, sample: int) -> list[str]:
    """Compare a random sample of records field by field -- counts alone would
    miss a column that copied as NULL or a value that changed type."""
    records = Base.metadata.tables["records"]
    cols = _columns(records)
    problems: list[str] = []
    with src.connect() as s, dst.connect() as d:
        # `ORDER BY random() LIMIT n` keeps only n ids at a time, so the sample
        # costs one scan of the table and no memory -- not a list of every id.
        ids = [
            r[0]
            for r in s.execute(
                select(records.c.id).order_by(func.random()).limit(sample)
            )
        ]
        for rid in ids:
            want = s.execute(select(*cols).where(records.c.id == rid)).one()
            got = d.execute(select(*cols).where(records.c.id == rid)).one_or_none()
            if got is None:
                problems.append(f"record {rid} is missing from the copy")
                continue
            for name in want._fields:
                if want._mapping[name] != got._mapping[name]:
                    problems.append(f"record {rid}: column '{name}' differs")
    return problems[:20]


def _analyze(engine: Engine) -> None:
    """Give the new database's query planner statistics. A freshly loaded
    database has none, and without them the planner can pick a table scan for
    a query an index would answer instantly."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("ANALYZE"))


def copy_database(
    source: Engine,
    target: Engine,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    batch: int = BATCH,
    sample: int = VERIFY_SAMPLE,
) -> CopyResult:
    """Copy every civex table from `source` to `target` and verify it.

    `target` must be empty (see `is_empty`) and at the same schema revision as
    `source`. Raises MoveCancelled if `cancel` is set; any exception leaves the
    target untouched, because the whole copy is one transaction. Does not
    raise on a failed verification -- the problems are on the result, so the
    caller decides what to tell the user and refuses to switch."""
    started = time.monotonic()
    report: ProgressFn = progress or (lambda p: None)

    src_tables = {t.name: t for t in app_tables(source)}
    tables = [t for t in app_tables(target) if t.name in src_tables]
    before = row_counts(source)
    total = sum(before.get(t.name, 0) for t in tables)
    state = Progress("copy", rows_total=total, tables_total=len(tables))
    report(state)

    with source.connect() as src_read:
        if source.dialect.name == "postgresql":
            # One snapshot for the whole read, so the copy is internally
            # consistent even while something else writes.
            src_read.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        depths = _schema_depths(src_read)
        with target.begin() as dst:
            for table in tables:
                state.table = table.name
                state.message = f"Copying {table.name}"
                report(state)

                def on_rows(n: int, _s: Progress = state) -> None:
                    _s.rows_done += n
                    report(_s)

                _copy_table(src_read, dst, table, depths, batch, on_rows, cancel)
                state.tables_done += 1
                report(state)
        src_read.rollback()

    state.phase, state.table, state.message = "verify", None, "Checking the copy"
    report(state)
    after = row_counts(target)
    problems = [
        f"{t.name}: {before[t.name]} rows in the original, {after.get(t.name, 0)} in the copy"
        for t in tables
        if before.get(t.name, 0) != after.get(t.name, 0)
    ]
    if not problems:
        problems = _sample_problems(source, target, sample)

    state.phase, state.message = "finalize", "Optimising the new database"
    report(state)
    _analyze(target)

    return CopyResult(
        counts={t.name: after.get(t.name, 0) for t in tables},
        seconds=time.monotonic() - started,
        problems=problems,
    )
