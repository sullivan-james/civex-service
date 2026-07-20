from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_db_status_shows_up_to_date_sqlite_project(project_dir: Path) -> None:
    result = runner.invoke(app, ["db", "status"])
    assert result.exit_code == 0
    assert "sqlite" in result.output
    assert "up to date" in result.output


def test_db_current_and_migrate_still_work(project_dir: Path) -> None:
    result = runner.invoke(app, ["db", "current"])
    assert result.exit_code == 0
    assert "Up to date" in result.output

    result = runner.invoke(app, ["db", "migrate"])
    assert result.exit_code == 0
    assert "OK" in result.output
