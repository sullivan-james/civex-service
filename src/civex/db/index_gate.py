"""Letting saves through while SQLite builds an index.

A `CREATE INDEX` on SQLite holds the database's write lock until it ends, and
ending takes as long as reading every record of the kind: about a minute for
a million records on an ordinary disk. Reading goes on meanwhile; a save waits
for the lock, and after the 30 s `busy_timeout` fails ("database is locked").
SQLite can't build an index a piece at a time, so a build gives way instead:

- While a host is keeping the indexes (`upkeep`), a marker sits beside the
  database file (`<db>-indexing`). Every connection's writes (the engine's
  `before_cursor_execute` hook calls `note_write`) then touch a second file
  (`<db>-indexing.wait`), in whatever process they are: the server, the CLI,
  a workflow run. Without the marker a write costs one `stat`.
- The build runs with a progress handler (`yielding`) that looks at that file
  every `CHECK_EVERY` steps of SQLite's machine and interrupts the build when
  a write has asked since it began. The interrupted build is rolled back at
  once (nothing of it was committed), the lock is free, and the save goes in:
  measured on a million records, a save waited 0.18 s instead of failing.
- The host starts the build again only once no write has asked for
  `QUIET_SECONDS` (`quiet_for`, in `IndexService.reconcile`). Under writes
  that never pause for that long an index waits; lists stay correct, just
  without its speed.

PostgreSQL builds `CONCURRENTLY` and never holds saves back, so none of this
applies there.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

CHECK_EVERY = 20_000  # SQLite VM steps between looks at the wait file
BUILDER = "civex_index_builder"  # in a connection's `info` while it builds
_WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE")


def _marker(db: str) -> Path:
    return Path(db + "-indexing")


def _wait(db: str) -> Path:
    return Path(db + "-indexing.wait")


def sqlite_file(url_database: str | None) -> str | None:
    """The database file a SQLite URL names, or None for one in memory."""
    if (
        not url_database
        or url_database == ":memory:"
        or url_database.startswith("file::memory:")
    ):
        return None
    return url_database


def note_write(db: str, statement: str) -> None:
    """Called before every statement on a SQLite connection that isn't the
    builder's: a write while an index build is under way asks it to give way."""
    if not statement.lstrip()[:7].upper().startswith(_WRITES):
        return
    if not _marker(db).exists():
        return
    wait = _wait(db)
    try:
        wait.touch()
    except OSError:  # a read-only folder: the build won't give way, saves wait
        pass


def quiet_for(db: str) -> float:
    """Seconds since a write last asked a build to give way (infinite when
    none has during this upkeep)."""
    try:
        return max(0.0, time.time() - _wait(db).stat().st_mtime)
    except OSError:
        return float("inf")


@contextmanager
def upkeep(db: str) -> Iterator[None]:
    """While the indexes are being kept: writes ask for their turn."""
    marker = _marker(db)
    _wait(db).unlink(missing_ok=True)
    try:
        marker.write_text(str(os.getpid()))
    except OSError:
        yield
        return
    try:
        yield
    finally:
        marker.unlink(missing_ok=True)
        _wait(db).unlink(missing_ok=True)


@contextmanager
def yielding(conn: Any, db: str) -> Iterator[None]:
    """Run a build on `conn` (a SQLAlchemy Connection) that is interrupted, by
    SQLite, as soon as a write elsewhere asks for its turn: the statement then
    raises an OperationalError saying "interrupted"."""
    dbapi = conn.connection.dbapi_connection
    started = time.time()
    wait = _wait(db)

    def asked() -> int:
        try:
            return 1 if wait.stat().st_mtime > started else 0
        except OSError:
            return 0

    conn.info[BUILDER] = True
    dbapi.set_progress_handler(asked, CHECK_EVERY)
    try:
        yield
    finally:
        dbapi.set_progress_handler(None, 0)
        conn.info.pop(BUILDER, None)


def is_interrupt(exc: BaseException) -> bool:
    return "interrupted" in str(exc)
