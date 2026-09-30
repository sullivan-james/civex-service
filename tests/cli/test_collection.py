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


def test_collection_timezone_create_show_update_clear(project_dir: Path) -> None:
    created = runner.invoke(
        app, ["collection", "create", "my-study", "--timezone", "America/Chicago"]
    )
    assert created.exit_code == 0, created.output
    assert (
        "America/Chicago"
        in runner.invoke(app, ["collection", "show", "my-study"]).output
    )

    updated = runner.invoke(
        app, ["collection", "update", "my-study", "--tz", "Asia/Kolkata"]
    )
    assert updated.exit_code == 0, updated.output
    assert (
        "Asia/Kolkata" in runner.invoke(app, ["collection", "show", "my-study"]).output
    )

    cleared = runner.invoke(app, ["collection", "update", "my-study", "--timezone", ""])
    assert cleared.exit_code == 0, cleared.output
    assert "not set" in runner.invoke(app, ["collection", "show", "my-study"]).output


def test_collection_invalid_timezone_fails(project_dir: Path) -> None:
    result = runner.invoke(
        app, ["collection", "create", "my-study", "--timezone", "Mars/Olympus"]
    )
    assert result.exit_code != 0
    assert "Unknown timezone" in result.output


def test_record_add_reads_naive_datetimes_in_the_collection_zone(
    project_dir: Path,
) -> None:
    from civex.config import load_config
    from civex.context import build_local_context

    runner.invoke(app, ["schema", "create", "sample"])
    runner.invoke(
        app, ["schema", "add-field", "sample", "taken_at", "--type", "datetime"]
    )
    runner.invoke(
        app, ["collection", "create", "my-study", "--timezone", "America/Chicago"]
    )
    added = runner.invoke(
        app,
        ["record", "add", "--to", "my-study", "--schema", "sample"],
        input="2024-03-01T15:30\n",
    )
    assert added.exit_code == 0, added.output

    ctx = build_local_context(load_config())
    try:
        (record,) = ctx.record_svc.find("my-study")
        assert record.data["taken_at"] == "2024-03-01T21:30:00+00:00"  # CST is UTC-6
    finally:
        ctx.close()
