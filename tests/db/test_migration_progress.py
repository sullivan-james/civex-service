"""A long upgrade says so: progress callback, pending list, CLI lines, the
SQLite cross-process lock, and the desktop page."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from civex.db import migrate


def _old_engine(tmp_path: Path, behind: int = 3) -> tuple[Engine, str]:
    """A SQLite database migrated to `behind` revisions before head."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    revisions = [
        r.revision for r in migrate._script_directory().walk_revisions("base", "head")
    ]
    target = revisions[behind]  # newest first
    cfg = migrate._alembic_config()
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        cfg.attributes["layout"] = None
        command.upgrade(cfg, target)
        connection.commit()
    return engine, target


def test_pending_migrations_lists_what_would_run(tmp_path: Path) -> None:
    engine, target = _old_engine(tmp_path)
    pending = migrate.pending_migrations(engine)
    assert len(pending) >= 3
    assert pending[-1][0] == migrate.head_revision()
    assert all(rev != target and desc for rev, desc in pending)
    # Asking changed nothing.
    assert migrate.pending_migrations(engine) == pending


def test_pending_migrations_empty_for_new_and_current_databases(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    assert migrate.pending_migrations(engine) == []
    migrate.ensure_schema_current(engine)
    assert migrate.pending_migrations(engine) == []


def test_progress_reports_every_pending_step_in_order(tmp_path: Path) -> None:
    engine, _ = _old_engine(tmp_path)
    pending = migrate.pending_migrations(engine)
    seen: list[tuple[int, int, str]] = []
    migrate.ensure_schema_current(engine, progress=lambda *a: seen.append(a))
    total = len(pending)
    assert seen == [(i + 1, total, desc) for i, (_, desc) in enumerate(pending)]
    assert migrate.pending_migrations(engine) == []


def test_no_progress_when_nothing_is_pending(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    seen: list = []
    migrate.ensure_schema_current(engine, progress=lambda *a: seen.append(a))
    assert seen == []


def test_reporting_progress_reaches_nested_callers(tmp_path: Path) -> None:
    engine, _ = _old_engine(tmp_path)
    seen: list = []
    with migrate.reporting_progress(lambda *a: seen.append(a)):
        migrate.ensure_schema_current(engine)
    assert seen and seen[0][0] == 1


def test_cli_prints_a_line_per_step_to_stderr(tmp_path: Path) -> None:
    from civex.cli.utils import stderr_migration_progress

    import contextlib
    import io

    buf = io.StringIO()
    report = stderr_migration_progress()
    with contextlib.redirect_stderr(buf):
        report(2, 5, "Add a thing")
    assert buf.getvalue().startswith(
        "Upgrading this project's database (step 2 of 5): Add a thing"
    )


def test_db_migrate_command_prints_steps_only_when_upgrading(project_dir: Path) -> None:
    import sqlite3

    from typer.testing import CliRunner

    from civex.main import app

    runner = CliRunner()
    quiet = runner.invoke(app, ["db", "migrate"])
    assert "Upgrading this project's database" not in quiet.output

    db = project_dir / "_civex" / "civex.db"
    revisions = [
        r.revision for r in migrate._script_directory().walk_revisions("base", "head")
    ]
    conn = sqlite3.connect(db)
    conn.execute("UPDATE alembic_version SET version_num = ?", (revisions[1],))
    conn.commit()
    conn.close()
    # head's last migration is replayed on an already-migrated database; the
    # point here is the notice, so tolerate a replay failing afterwards.
    result = runner.invoke(app, ["db", "migrate"])
    assert "Upgrading this project's database (step 1 of 1)" in result.output


def test_sqlite_lock_makes_a_second_process_wait(tmp_path: Path) -> None:
    engine, _ = _old_engine(tmp_path)  # the lock is taken only to upgrade
    messages: list[tuple[int, int, str]] = []
    entered = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with engine.connect() as connection:
            with migrate._cross_process_lock(connection):
                entered.set()
                release.wait(10)

    t = threading.Thread(target=holder)
    t.start()
    assert entered.wait(5)
    acquired = threading.Event()

    def waiter() -> None:
        with engine.connect() as connection:
            with migrate._cross_process_lock(connection, lambda *a: messages.append(a)):
                acquired.set()

    w = threading.Thread(target=waiter)
    w.start()
    time.sleep(0.5)
    assert not acquired.is_set()
    assert (
        messages and messages[0][0] == 0 and "another civex" in messages[0][2].lower()
    )
    release.set()
    t.join(5)
    w.join(5)
    assert acquired.is_set()


def test_tray_upgrades_before_serving_without_the_30s_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import civex.desktop.tray as tray
    from civex.project import scaffold_project

    scaffold_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    class Window:
        pages: list[str] = []

        def load_html(self, text: str) -> None:
            self.pages.append(text)

    window = Window()
    window.pages = []
    # Pretend the project is behind: two steps pending, applied by a stub.
    monkeypatch.setattr(
        migrate, "pending_migrations", lambda engine: [("a", "First"), ("b", "Second")]
    )

    def fake_ensure(engine, layout=None, *, progress=None):
        progress(1, 2, "First")
        progress(2, 2, "Second")

    monkeypatch.setattr(migrate, "ensure_schema_current", fake_ensure)
    assert tray._upgrade_before_serving(window, tmp_path) is None
    assert len(window.pages) == 2
    assert "step 1 of 2: First" in window.pages[0]
    assert "step 2 of 2: Second" in window.pages[1]
    assert "Large projects can take several minutes" in window.pages[1]
    assert "nothing is lost" in window.pages[1]

    def failing(engine, layout=None, *, progress=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(migrate, "ensure_schema_current", failing)
    assert tray._upgrade_before_serving(window, tmp_path) == "disk full"


def test_tray_launch_shows_the_error_page_when_the_upgrade_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import civex.desktop.tray as tray

    pages: list[str] = []

    class Window:
        def load_html(self, text: str) -> None:
            pages.append(text)

        def load_url(self, url: str) -> None:
            pages.append("url")

    monkeypatch.setattr(tray, "_window", Window())
    monkeypatch.setattr(tray, "_save_recent", lambda p: None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tray, "_upgrade_before_serving", lambda w, p: "disk full")
    started: list = []
    monkeypatch.setattr(tray._server, "start", lambda *a: started.append(a))
    tray._launch_project(tmp_path)
    deadline = time.monotonic() + 5
    while not pages and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "disk full" in pages[-1]
    assert not started
