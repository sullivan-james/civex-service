from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_record_add_and_find(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    runner.invoke(app, ["schema", "add-field", "trial", "subject", "--type", "string"])
    runner.invoke(app, ["collection", "create", "study"])

    # Provide field value via stdin
    result = runner.invoke(app, ["record", "add", "--to", "study", "--schema", "trial"], input="S01\n")
    assert result.exit_code == 0

    result = runner.invoke(app, ["record", "find", "--in", "study"])
    assert result.exit_code == 0
    assert "trial" in result.output  # schema name appears in the summary table


def test_record_not_found_exits_nonzero(project_dir: Path) -> None:
    result = runner.invoke(app, ["record", "show", "nonexistent-id"])
    assert result.exit_code != 0


def test_record_add_to_missing_collection_fails(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    result = runner.invoke(app, ["record", "add", "--to", "nonexistent", "--schema", "trial"])
    assert result.exit_code != 0
