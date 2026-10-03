from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_schema_create_and_list(project_dir: Path) -> None:
    result = runner.invoke(
        app, ["schema", "create", "trial", "--description", "A trial"]
    )
    assert result.exit_code == 0

    result = runner.invoke(app, ["schema", "list"])
    assert result.exit_code == 0
    assert "trial" in result.output


def test_schema_add_field(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    result = runner.invoke(
        app,
        ["schema", "add-field", "trial", "subject", "--type", "string", "--required"],
    )
    assert result.exit_code == 0

    result = runner.invoke(app, ["schema", "show", "trial"])
    assert result.exit_code == 0
    assert "subject" in result.output


def test_schema_inheritance(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "base"])
    runner.invoke(app, ["schema", "add-field", "base", "subject", "--type", "string"])
    runner.invoke(app, ["schema", "create", "child", "--parent", "base"])

    result = runner.invoke(app, ["schema", "show", "child"])
    assert result.exit_code == 0
    assert "subject" in result.output


def test_schema_create_duplicate_name_fails(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    result = runner.invoke(app, ["schema", "create", "trial"])
    assert result.exit_code != 0


def test_schema_add_field_unknown_dtype_fails(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    result = runner.invoke(
        app, ["schema", "add-field", "trial", "subject", "--type", "not-a-real-type"]
    )
    assert result.exit_code != 0
