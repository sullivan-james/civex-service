"""`civex schema add-unique / unique / remove-unique`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def _plot(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "plot"])
    runner.invoke(app, ["schema", "add-field", "plot", "site", "--type", "string"])
    runner.invoke(app, ["schema", "add-field", "plot", "number", "--type", "integer"])


def test_add_list_and_remove_a_key(project_dir: Path) -> None:
    _plot(project_dir)
    added = runner.invoke(app, ["schema", "add-unique", "plot", "site", "number"])
    assert added.exit_code == 0, added.output

    listed = runner.invoke(app, ["schema", "unique", "plot"])
    assert "site, number" in listed.output
    assert (
        "Unique: site, number" in runner.invoke(app, ["schema", "show", "plot"]).output
    )

    removed = runner.invoke(app, ["schema", "remove-unique", "plot", "number", "site"])
    assert removed.exit_code == 0, removed.output
    assert (
        "no uniqueness keys" in runner.invoke(app, ["schema", "unique", "plot"]).output
    )


def test_a_bad_field_is_reported_not_a_traceback(project_dir: Path) -> None:
    _plot(project_dir)
    result = runner.invoke(app, ["schema", "add-unique", "plot", "nope"])
    assert result.exit_code == 1
    assert "nope" in result.output


def test_removing_a_key_that_is_not_there_says_so(project_dir: Path) -> None:
    _plot(project_dir)
    result = runner.invoke(app, ["schema", "remove-unique", "plot", "site"])
    assert result.exit_code == 1
    assert "no uniqueness key" in result.output
