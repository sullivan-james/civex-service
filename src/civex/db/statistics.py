"""The query planner's statistics: when civex refreshes them, decided here.

SQLite's planner chooses between indexes from the statistics `ANALYZE` keeps
(`sqlite_stat1`), and with none it may ignore an expression index entirely and
sort a million records instead: measured, a sort by a field went from ~150 ms
to 0.1 ms on 300k records once statistics existed. Nothing refreshes them by
itself, so civex does, at these moments:

- `INDEX_BUILT`: after a managed field index is made, the table is analysed
  (on SQLite with `analysis_limit`, so it reads a sample, not every row);
- `BULK_WRITE`: after an import, a bundle import or another bulk change,
  `PRAGMA optimize` re-analyses whatever has changed enough to matter;
- `PERIODIC`: the server does the same about once an hour (`index_jobs`), and
  every SQLite connection does it as it closes (`db/engine.py`), which is
  SQLite's own advice for applications.

PostgreSQL's autovacuum keeps its statistics, so only a new index asks for an
`ANALYZE records` there (so it is used straight away).
"""

from __future__ import annotations

import logging

from sqlalchemy.engine import Connection

from civex.domain.field_index import INDEX_BUILT

log = logging.getLogger(__name__)

# Rows SQLite reads per index when it analyses: enough for the planner to tell
# a selective index from an unselective one, cheap at any size (SQLite's own
# suggestion is a few hundred to a thousand).
ANALYSIS_LIMIT = 1000


def sqlite_optimize(dbapi_connection) -> None:
    """`PRAGMA optimize` on a raw SQLite connection, ignoring any failure (it
    is only ever an improvement)."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"PRAGMA analysis_limit={ANALYSIS_LIMIT}")
        cursor.execute("PRAGMA optimize")
        cursor.close()
    except Exception as e:  # noqa: BLE001 - a closed or busy database: next time
        log.debug("PRAGMA optimize skipped: %s", e)


def refresh(conn: Connection, reason: str) -> None:
    """Bring the planner's statistics up to date after `reason`, on `conn`
    (on SQLite, the caller's own connection: ANALYZE is transactional there).
    Never fails the work it follows."""
    try:
        _refresh(conn, reason)
    except Exception as e:  # noqa: BLE001 - statistics are only an improvement
        log.warning("refreshing query statistics failed: %s", e)


def _refresh(conn: Connection, reason: str) -> None:
    if conn.dialect.name == "postgresql":
        if reason == INDEX_BUILT:
            conn.exec_driver_sql("ANALYZE records")
        return
    conn.exec_driver_sql(f"PRAGMA analysis_limit={ANALYSIS_LIMIT}")
    if reason == INDEX_BUILT:
        conn.exec_driver_sql("ANALYZE records")
    else:
        conn.exec_driver_sql("PRAGMA optimize")
