from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_license_works_without_a_civex_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["license"])
    assert result.exit_code == 0
    assert "PolyForm Shield License" in result.output


def test_policy_list_empty_message(project_dir: Path) -> None:
    result = runner.invoke(app, ["policy", "list"])
    assert result.exit_code == 0
    assert "No policy documents" in result.output


def test_policy_show_unknown_stem_errors(project_dir: Path) -> None:
    result = runner.invoke(app, ["policy", "show", "nope"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_policy_list_and_show(project_dir: Path) -> None:
    policies_dir = project_dir / "_civex" / "policies"
    policies_dir.mkdir(parents=True)
    (policies_dir / "data-handling.md").write_text(
        "# Data Handling Policy\n\nDe-identify before export.\n"
    )

    list_result = runner.invoke(app, ["policy", "list"])
    assert list_result.exit_code == 0
    assert "data-handling" in list_result.output
    assert "Data Handling Policy" in list_result.output

    show_result = runner.invoke(app, ["policy", "show", "data-handling"])
    assert show_result.exit_code == 0
    assert "De-identify before export." in show_result.output
