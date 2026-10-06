"""How much room the database file takes and how much of it is free, and giving
the free part back. SQLite only: it keeps freed pages inside its file (so a
smaller history doesn't shrink it) until VACUUM rewrites the file. PostgreSQL
reclaims space by itself."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine


@dataclass
class DbSpace:
    size_bytes: int  # the file
    free_bytes: int  # inside it, unused: what reclaiming gives back


class LocalDbSpace:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def space(self) -> DbSpace | None:
        if self._engine.dialect.name != "sqlite":
            return None
        with self._engine.connect() as conn:
            page = conn.exec_driver_sql("PRAGMA page_size").scalar() or 0
            pages = conn.exec_driver_sql("PRAGMA page_count").scalar() or 0
            free = conn.exec_driver_sql("PRAGMA freelist_count").scalar() or 0
        return DbSpace(size_bytes=page * pages, free_bytes=page * free)

    def reclaim(self) -> None:
        """Rewrite the file without its free pages. It needs about as much free
        disk as the file while it runs, and holds the database meanwhile."""
        if self._engine.dialect.name != "sqlite":
            return
        with self._engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as conn:
            conn.exec_driver_sql("VACUUM")
