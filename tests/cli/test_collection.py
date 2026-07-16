from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_dataset_create_and_list(project_dir: Path) -> None:
    result = runner.invoke(app, ["collection", "create", "my-study"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["collection", "list"])
    assert result.exit_code == 0
    assert "my-study" in result.output


def test_collection_create_duplicate_name_fails(project_dir: Path) -> None:
    runner.invoke(app, ["collection", "create", "my-study"])
    result = runner.invoke(app, ["collection", "create", "my-study"])
    assert result.exit_code != 0
