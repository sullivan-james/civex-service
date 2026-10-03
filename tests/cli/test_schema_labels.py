"""CLI surface for the name/label split: --label, slug enforcement, and lint."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_create_with_label_shows_the_label_and_the_name(project_dir: Path) -> None:
    result = runner.invoke(
        app,
        ["schema", "create", "acoustic_recording", "--label", "Acoustic Recording"],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["schema", "show", "acoustic_recording"])
    assert result.exit_code == 0, result.output
    assert "Acoustic Recording" in result.output
    assert "acoustic_recording" in result.output


def test_create_rejects_a_non_slug_name_and_suggests_one(project_dir: Path) -> None:
    result = runner.invoke(app, ["schema", "create", "Acoustic Recording"])
    assert result.exit_code == 1
    assert "acoustic_recording" in result.output


def test_add_field_with_label(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    result = runner.invoke(
        app,
        [
            "schema",
            "add-field",
            "trial",
            "recording_date",
            "--type",
            "date",
            "--label",
            "Recording Date",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["schema", "show", "trial"])
    assert "Recording Date" in result.output
    assert "recording_date" in result.output


def test_add_field_rejects_a_non_slug_name(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    result = runner.invoke(
        app, ["schema", "add-field", "trial", "Recording Date", "--type", "date"]
    )
    assert result.exit_code == 1
    assert "recording_date" in result.output


def test_update_label_without_renaming(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    runner.invoke(app, ["schema", "add-field", "trial", "subject", "--type", "string"])

    assert (
        runner.invoke(
            app, ["schema", "update", "trial", "--label", "Clinical Trial"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["schema", "update-field", "trial", "subject", "--label", "Subject ID"],
        ).exit_code
        == 0
    )

    result = runner.invoke(app, ["schema", "show", "trial"])
    assert "Clinical Trial" in result.output
    assert "Subject ID" in result.output


def test_lint_is_quiet_when_every_name_is_a_slug(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    runner.invoke(app, ["schema", "add-field", "trial", "subject", "--type", "string"])

    result = runner.invoke(app, ["schema", "lint"])
    assert result.exit_code == 0, result.output
    assert "valid slugs" in result.output


def test_lint_reports_legacy_names(project_dir: Path) -> None:
    # Only a restore path can produce these, so seed one through the service.
    from civex.config import load_config
    from civex.context import build_local_context

    ctx = build_local_context(load_config())
    ctx.schema_svc.create("Legacy Schema", allow_legacy_name=True)
    ctx.schema_svc.add_field(
        "Legacy Schema", "Legacy Field", "string", allow_legacy_name=True
    )
    ctx.commit()
    ctx.close()

    result = runner.invoke(app, ["schema", "lint"])
    assert result.exit_code == 0, result.output
    assert "legacy_schema" in result.output
    assert "legacy_field" in result.output
    assert "2 name(s)" in result.output
