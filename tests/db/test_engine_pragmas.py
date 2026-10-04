"""Per-connection SQLite settings applied by `enable_sqlite_foreign_keys`."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from civex.db.engine import SQLITE_BUSY_TIMEOUT_MS, enable_sqlite_foreign_keys


def test_connections_wait_for_a_competing_writer_and_enforce_foreign_keys(
    tmp_path: Path,
) -> None:
    engine = enable_sqlite_foreign_keys(create_engine(f"sqlite:///{tmp_path / 'a.db'}"))
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == (
            SQLITE_BUSY_TIMEOUT_MS
        )
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        # WAL is deliberately not enabled: it breaks copying the database file.
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "delete"
