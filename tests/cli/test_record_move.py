"""civex record move / move-all: the same move as the API, from a terminal."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def _setup() -> str:
    for args in (
        ["schema", "create", "site"],
        ["schema", "add-field", "site", "name", "--type", "string"],
        ["schema", "create", "visit", "--parent", "site"],
        ["collection", "create", "survey"],
        ["collection", "create", "archive"],
    ):
        assert runner.invoke(app, args).exit_code == 0, args
    result = runner.invoke(
        app, ["record", "add", "--to", "survey", "--schema", "site"], input="a\n"
    )
    assert result.exit_code == 0, result.output
    return result.output.split("Added record ")[1].split(".")[0].strip()


def test_move_says_what_it_did(project_dir: Path) -> None:
    site = _setup()
    result = runner.invoke(
        app, ["record", "move", site, "--to", "archive", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "would move to 'archive'" in result.output

    result = runner.invoke(app, ["record", "move", site[:8], "--to", "archive"])
    assert result.exit_code == 0, result.output
    assert "Moved 1 record(s)" in result.output
    assert "site" in runner.invoke(app, ["record", "find", "--in", "archive"]).output
    assert "site" not in runner.invoke(app, ["record", "find", "--in", "survey"]).output


def test_move_all_moves_a_collection(project_dir: Path) -> None:
    _setup()
    result = runner.invoke(
        app,
        ["record", "move-all", "survey", "--to", "archive", "--schema", "site", "-y"],
    )
    assert result.exit_code == 0, result.output
    assert "Moved 1 record(s)" in result.output
    assert (
        runner.invoke(app, ["record", "find", "--in", "survey"]).output.count("site")
        == 0
    )


def test_a_refused_move_exits_nonzero_with_the_reason(project_dir: Path) -> None:
    _setup()
    result = runner.invoke(app, ["record", "move", "nope", "--to", "nowhere"])
    assert result.exit_code == 1
    assert "not found" in result.output
