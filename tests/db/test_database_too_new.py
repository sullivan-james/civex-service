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
    """Output with Rich's line wrapping and panel borders undone."""
    return " ".join(result.output.replace("│", " ").split())


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
    assert "newer civex" in _text(result)
    assert "civex update" in _text(result)
    assert "ffffffffffff" in _text(result)
    assert "Can't locate revision" not in _text(result)


def test_the_message_is_a_panel_with_the_facts_and_the_fix(newer_db: Path) -> None:
    from civex import __version__

    text = _text(runner.invoke(app, ["schema", "list"]))
    assert "Database is from a newer civex" in text
    assert "civex.db" in text
    assert "ffffffffffff" in text
    assert __version__ in text
    assert "What to do" in text
    assert "civex update" in text
    assert "hasn't been changed" in text


def test_serve_refuses_before_starting(
    newer_db: Path, monkeypatch, tmp_path: Path
) -> None:
    import uvicorn

    from civex import running

    monkeypatch.setenv("CIVEX_USER_STATE", str(tmp_path / "state" / "sync.toml"))
    started: list[object] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(1))
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 1
    assert "Database is from a newer civex" in _text(result)
    assert started == []
    # A server that never ran says nothing about running (an update would
    # find it and offer to stop it).
    assert not running.running_dir().exists() or not list(
        running.running_dir().iterdir()
    )


def test_the_api_answers_503_with_the_details(newer_db: Path) -> None:
    from fastapi.testclient import TestClient

    from civex.server.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/schemas")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "database_too_new"
    assert body["revisions"] == ["ffffffffffff"]
    assert "newer version of civex" in body["detail"]


def test_other_commands_explain_it_too(newer_db: Path) -> None:
    result = runner.invoke(app, ["schema", "list"])
    assert result.exit_code == 1
    assert "newer civex" in _text(result)
    assert "Traceback" not in _text(result)


def test_status_says_the_database_is_newer(newer_db: Path) -> None:
    result = runner.invoke(app, ["db", "current"])
    assert result.exit_code == 1
    assert "newer civex" in _text(result)
    assert "Pending migrations" not in _text(result)


def test_db_status_does_not_call_it_a_pending_migration(newer_db: Path) -> None:
    result = runner.invoke(app, ["db", "status"])
    assert "from a newer civex" in _text(result)
    assert "pending migrations" not in _text(result)


def test_the_database_is_left_untouched(newer_db: Path) -> None:
    runner.invoke(app, ["db", "migrate"])
    conn = sqlite3.connect(newer_db)
    try:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "ffffffffffff",
        )
    finally:
        conn.close()
