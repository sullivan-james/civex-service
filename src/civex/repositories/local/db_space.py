"""How much room the database takes and how much of it is empty, and giving the
empty part back.

SQLite keeps freed pages inside its file until VACUUM rewrites it. PostgreSQL
makes dead space reusable (autovacuum) but never shrinks a table, so a table
that once held much more than it holds now stays big; only VACUUM FULL gives it
back. On PostgreSQL both figures are for the connection's current schema (a
host that keeps a project per schema must not report, or vacuum, its
neighbours), and the empty space is an estimate from the catalogs, never a scan.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from civex.domain import features
from civex.domain.exceptions import FeatureUnavailableError

# A table is worth rewriting when the estimate says this much of it is empty.
WORTH_BYTES = 50 * 1024 * 1024
WORTH_FRACTION = 0.30
MIN_BYTES = 1024 * 1024  # but never for less than this

# Per table of the current schema (partitioned parents hold no data; their
# leaves are listed). Heap bytes less what the live rows should take: the
# planner's row count (reltuples; -1 = never analyzed, so no estimate) times
# the average row width from pg_stats plus the 24-byte header and 4-byte item
# pointer, spread over the fill factor. Indexes are rewritten too, so the size
# is the total relation's, but only the heap's empty space is estimated.
_TABLES_SQL = """
SELECT c.relname, n.nspname,
       pg_total_relation_size(c.oid) AS total,
       GREATEST(0, pg_relation_size(c.oid) - CASE WHEN c.reltuples < 0 OR NOT EXISTS (SELECT 1 FROM pg_stats s2
               WHERE s2.schemaname = n.nspname AND s2.tablename = c.relname) THEN pg_relation_size(c.oid)
           ELSE (c.reltuples * (28 + COALESCE((SELECT sum(s.avg_width) FROM pg_stats s
               WHERE s.schemaname = n.nspname AND s.tablename = c.relname), 0))
               / COALESCE((SELECT substring(o FROM 'fillfactor=(\\d+)')::int
                   FROM unnest(c.reloptions) o WHERE left(o, 11) = 'fillfactor='), 100) * 100)::bigint
           END) AS empty
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'm')
"""


@dataclass
class TableSpace:
    name: str
    size_bytes: int  # with its indexes
    free_bytes: int  # estimated empty part
    schema: str = ""  # where it is (PostgreSQL)


@dataclass
class DbSpace:
    size_bytes: int  # the file (SQLite) or the schema's tables (PostgreSQL)
    free_bytes: int  # inside it, unused: what reclaiming gives back
    estimate: bool = False  # free_bytes is an estimate (PostgreSQL)
    # PostgreSQL: the tables a reclaim would rewrite (SQLite: empty).
    tables: list[TableSpace] = field(default_factory=list)
    can_reclaim: bool = True  # False where the host doesn't offer it


class LocalDbSpace:
    def __init__(self, engine: Engine, *, may_vacuum_full: bool = True) -> None:
        self._engine = engine
        # PostgreSQL's VACUUM FULL locks a table; a host sharing a cluster
        # between tenants leaves `features.DB_ADMIN` off to refuse it.
        self._may_vacuum_full = may_vacuum_full

    def _postgres_tables(self) -> list[TableSpace]:
        with self._engine.connect() as conn:
            rows = conn.exec_driver_sql(_TABLES_SQL).all()
            conn.rollback()
        return [TableSpace(r[0], int(r[2] or 0), int(r[3] or 0), r[1]) for r in rows]

    @staticmethod
    def _worth(t: TableSpace) -> bool:
        return t.free_bytes >= MIN_BYTES and (
            t.free_bytes >= WORTH_BYTES or t.free_bytes >= WORTH_FRACTION * t.size_bytes
        )

    def space(self) -> DbSpace | None:
        dialect = self._engine.dialect.name
        if dialect == "postgresql":
            try:
                tables = self._postgres_tables()
            except SQLAlchemyError:
                return None  # can't measure (permissions, timeout): say nothing
            return DbSpace(
                size_bytes=sum(t.size_bytes for t in tables),
                free_bytes=sum(t.free_bytes for t in tables),
                estimate=True,
                tables=sorted(
                    (t for t in tables if self._worth(t)),
                    key=lambda t: -t.free_bytes,
                ),
                can_reclaim=self._may_vacuum_full,
            )
        if dialect != "sqlite":
            return None
        with self._engine.connect() as conn:
            page = conn.exec_driver_sql("PRAGMA page_size").scalar() or 0
            pages = conn.exec_driver_sql("PRAGMA page_count").scalar() or 0
            free = conn.exec_driver_sql("PRAGMA freelist_count").scalar() or 0
        return DbSpace(size_bytes=page * pages, free_bytes=page * free)

    def reclaim(self) -> list[str]:
        """Rewrite the file (SQLite) or the tables worth it (PostgreSQL) without
        their empty space. SQLite needs about the file's size in free disk and
        holds the database; PostgreSQL rewrites one table at a time, each locked
        (reads too) while it runs, and needs about that table's size. Returns
        the tables skipped because another session held a lock (PostgreSQL)."""
        dialect = self._engine.dialect.name
        if dialect == "postgresql":
            if not self._may_vacuum_full:
                raise FeatureUnavailableError(features.DB_ADMIN)
            quote = self._engine.dialect.identifier_preparer.quote
            # Schema names come from the same catalog query as the tables, not
            # from this connection (a host may route with SET LOCAL, which an
            # AUTOCOMMIT connection doesn't see).
            todo = [t for t in self._postgres_tables() if self._worth(t)]
            with self._engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as conn:
                skipped: list[str] = []
                try:
                    # Waiting for the lock queues every reader behind it: give up.
                    conn.exec_driver_sql("SET lock_timeout = '5s'")
                    for t in sorted(todo, key=lambda t: -t.free_bytes):
                        try:
                            conn.exec_driver_sql(
                                f"VACUUM (FULL) {quote(t.schema)}.{quote(t.name)}"
                            )
                        except OperationalError as e:
                            # Busy: this one is left for next time, the rest go on.
                            if "lock" not in str(e).lower():
                                raise
                            skipped.append(t.name)
                finally:
                    conn.exec_driver_sql("RESET lock_timeout")
            return skipped
        if dialect != "sqlite":
            return []
        with self._engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as conn:
            conn.exec_driver_sql("VACUUM")
        return []
