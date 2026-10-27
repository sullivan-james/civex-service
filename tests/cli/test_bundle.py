"""`civex bundle export|show|import` move a project's data between projects;
`civex dump`/`restore` say what replaced them."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.config import load_config
from civex.context import build_local_context
from civex.main import app

runner = CliRunner()


def test_export_show_and_import_into_another_project(
    project_dir: Path, tmp_path_factory, monkeypatch
) -> None:
    ctx = build_local_context(load_config())
    ctx.schema_svc.create("species")
    ctx.schema_svc.add_field("species", "common_name", "string")
    ctx.dataset_svc.create("study", timezone="Europe/London")
    ref = ctx.file_svc.store_bytes(b"bytes", "a.txt")
    ctx.schema_svc.add_field("species", "doc", "file")
    seal = ctx.record_svc.add(
        "study", "species", {"common_name": "Grey seal", "doc": ref.to_dict()}
    )
    ctx.commit()
    ctx.close()

    bundle = project_dir / "study.civex.zip"
    dry = runner.invoke(app, ["bundle", "export", "-o", str(bundle), "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert not bundle.exists() and "Would export" in dry.output
    result = runner.invoke(app, ["bundle", "export", "-o", str(bundle)])
    assert result.exit_code == 0, result.output
    assert bundle.exists()

    shown = runner.invoke(app, ["bundle", "show", str(bundle)])
    assert shown.exit_code == 0, shown.output
    assert "species" in shown.output and "study" in shown.output

    other = tmp_path_factory.mktemp("other")
    monkeypatch.chdir(other)
    assert runner.invoke(app, ["init", "--sqlite", str(other)]).exit_code == 0
    result = runner.invoke(app, ["bundle", "import", str(bundle), "--yes"])
    assert result.exit_code == 0, result.output
    assert "1 added" in result.output

    ctx = build_local_context(load_config())
    try:
        assert ctx.dataset_svc.get("study").timezone == "Europe/London"
        record = ctx.record_svc.get(str(seal.id))
        assert record.data["common_name"] == "Grey seal"
        assert ctx.file_svc.retrieve(ref.sha256) == b"bytes"
    finally:
        ctx.close()


def test_a_file_that_is_not_a_bundle_is_refused(project_dir: Path) -> None:
    bad = project_dir / "notes.zip"
    bad.write_text("hello")
    result = runner.invoke(app, ["bundle", "import", str(bad), "--yes"])
    assert result.exit_code == 1
    assert "not a civex bundle" in result.output


def test_dump_and_restore_point_at_bundle(project_dir: Path) -> None:
    result = runner.invoke(app, ["dump"])
    assert result.exit_code == 1 and "civex bundle export" in result.output
    result = runner.invoke(app, ["restore", "x.yaml"])
    assert result.exit_code == 1 and "civex bundle import" in result.output
