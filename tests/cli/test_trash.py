from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_schema_delete_restore_purge(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "animal"])

    result = runner.invoke(app, ["schema", "delete", "animal", "--yes"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["schema", "list"])
    assert "animal" not in result.output

    result = runner.invoke(app, ["trash", "list"])
    assert result.exit_code == 0
    assert "animal" in result.output

    result = runner.invoke(app, ["schema", "restore", "animal"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["schema", "list"])
    assert "animal" in result.output

    runner.invoke(app, ["schema", "delete", "animal", "--yes"])
    result = runner.invoke(app, ["schema", "purge", "animal", "--yes"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["trash", "list"])
    assert "Recently Deleted is empty" in result.output


def test_record_delete_cascades_to_schema_delete(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "animal"])
    runner.invoke(app, ["collection", "create", "zoo"])
    add_result = runner.invoke(
        app, ["record", "add", "--to", "zoo", "--schema", "animal"], input=""
    )
    assert add_result.exit_code == 0

    runner.invoke(app, ["schema", "delete", "animal", "--yes"])

    find_result = runner.invoke(app, ["record", "find", "--in", "zoo"])
    assert "No records match" in find_result.output

    trash_result = runner.invoke(app, ["trash", "list"])
    assert "schema" in trash_result.output
    assert "record" in trash_result.output


def test_purge_expired_reports_when_nothing_eligible(project_dir: Path) -> None:
    runner.invoke(app, ["collection", "create", "zoo"])
    runner.invoke(app, ["collection", "delete", "zoo", "--yes"])

    result = runner.invoke(app, ["trash", "purge-expired", "--yes"])
    assert result.exit_code == 0
    assert "Nothing is past the retention window" in result.output


def test_trash_list_shows_a_bulk_delete_as_one_line_and_filters(
    project_dir: Path,
) -> None:
    runner.invoke(app, ["schema", "create", "animal"])
    runner.invoke(app, ["collection", "create", "zoo"])
    for _ in range(3):
        runner.invoke(
            app, ["record", "add", "--to", "zoo", "--schema", "animal"], input=""
        )
    runner.invoke(app, ["record", "delete-all", "zoo", "--yes"])

    listing = runner.invoke(app, ["trash", "list"])
    assert listing.exit_code == 0
    assert "batch" in listing.output  # the three, deleted together, are one line
    assert "3 record(s)" in listing.output

    by_kind = runner.invoke(app, ["trash", "list", "--kind", "schema"])
    assert "No matches" in by_kind.output
    bad = runner.invoke(app, ["trash", "list", "--kind", "nonsense"])
    assert bad.exit_code == 1
