from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def _tomorrow() -> str:
    return (date.today() + timedelta(days=2)).isoformat()


def _deleted_records(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "animal"])
    runner.invoke(app, ["collection", "create", "zoo"])
    for _ in range(2):
        runner.invoke(
            app, ["record", "add", "--to", "zoo", "--schema", "animal"], input=""
        )
    runner.invoke(app, ["record", "delete-all", "zoo", "--yes"])


def test_show_says_what_is_kept_and_what_would_go(project_dir: Path) -> None:
    result = runner.invoke(app, ["retention", "show"])
    assert result.exit_code == 0, result.output
    assert "forever" in result.output
    assert "Nothing is old enough" in result.output


def test_run_needs_to_be_told_what_to_clean_up(project_dir: Path) -> None:
    result = runner.invoke(app, ["retention", "run"])
    assert result.exit_code == 1
    assert "Say what to clean up" in result.output


def test_run_previews_asks_and_then_deletes(project_dir: Path) -> None:
    _deleted_records(project_dir)
    declined = runner.invoke(
        app, ["retention", "run", "--deleted-before", _tomorrow()], input="n\n"
    )
    assert declined.exit_code != 0
    assert "Would remove" in declined.output
    still = runner.invoke(app, ["trash", "list"])
    assert "batch" in still.output  # still deleted, still restorable

    done = runner.invoke(
        app, ["retention", "run", "--deleted-before", _tomorrow(), "--yes"]
    )
    assert done.exit_code == 0, done.output
    assert "Removed" in done.output
    assert "Recently Deleted is empty" in runner.invoke(app, ["trash", "list"]).output


def test_a_dry_run_changes_nothing(project_dir: Path) -> None:
    _deleted_records(project_dir)
    result = runner.invoke(
        app, ["retention", "run", "--deleted-before", _tomorrow(), "--dry-run"]
    )
    assert result.exit_code == 0 and "Would remove" in result.output
    assert "batch" in runner.invoke(app, ["trash", "list"]).output


def test_a_bad_date_is_refused(project_dir: Path) -> None:
    result = runner.invoke(app, ["retention", "run", "--history-before", "last week"])
    assert result.exit_code == 1
    assert "must be a date" in result.output


def test_forget_purged_has_nothing_to_do_after_a_normal_purge(
    project_dir: Path,
) -> None:
    _deleted_records(project_dir)
    runner.invoke(app, ["retention", "run", "--deleted-before", _tomorrow(), "--yes"])
    result = runner.invoke(app, ["retention", "forget-purged", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Nothing to delete" in result.output
