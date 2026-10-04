"""A database stamped by a newer civex gets a plain explanation, not
alembic's "Can't locate revision"."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def _text(result) -> str:
    """Output with Rich's line wrapping undone."""
    return " ".join(result.output.split())


@pytest.fixture()
def newer_db(project_dir: Path) -> Path:
    """The project's database, restamped as if a newer civex had migrated it."""
    db = project_dir / "_civex" / "civex.db"
    conn = sqlite3.connect(db)
    conn.execute("UPDATE alembic_version SET version_num = 'ffffffffffff'")
    conn.commit()
    conn.close()
    return db


def test_migrate_explains_a_newer_database(newer_db: Path) -> None:
    result = runner.invoke(app, ["db", "migrate"])
    assert result.exit_code == 1
    assert "newer version of civex" in _text(result)
    assert "civex update" in _text(result)
    assert "ffffffffffff" in _text(result)
    assert "Can't locate revision" not in _text(result)


def test_other_commands_explain_it_too(newer_db: Path) -> None:
    result = runner.invoke(app, ["schema", "list"])
    assert result.exit_code == 1
    assert "newer version of civex" in _text(result)
    assert "Traceback" not in _text(result)


def test_status_says_the_database_is_newer(newer_db: Path) -> None:
    result = runner.invoke(app, ["db", "current"])
    assert result.exit_code == 1
    assert "newer civex" in _text(result)
    assert "Pending migrations" not in _text(result)


def test_the_database_is_left_untouched(newer_db: Path) -> None:
    runner.invoke(app, ["db", "migrate"])
    conn = sqlite3.connect(newer_db)
    try:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "ffffffffffff",
        )
    finally:
        conn.close()
