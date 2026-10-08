"""CIVEX-168: dump restore passes parent_record_id straight through to
RecordService.add() (src/civex/cli/dump.py), so a crafted or corrupted dump
must not be able to create a record whose parent lives in a different
dataset."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from civex.context import AppContext, build_local_context
from civex.config import load_config
from civex.main import app

runner = CliRunner()


def test_restore_rejects_record_with_cross_dataset_parent_link(
    project_dir: Path,
) -> None:
    ctx: AppContext = build_local_context(load_config())
    ctx.dataset_svc.create("ds1")
    ctx.dataset_svc.create("ds2")
    ctx.schema_svc.create("trigger")
    ctx.schema_svc.create("child", parent="trigger")
    trigger = ctx.record_svc.add("ds1", "trigger", {})
    ctx.commit()
    ctx.close()

    dump_doc = {
        "civex_version": "0.0.0",
        "exported_at": "2026-01-01T00:00:00+00:00",
        "schemas": [
            {"name": "trigger", "description": None, "parent": None, "fields": []},
            {"name": "child", "description": None, "parent": "trigger", "fields": []},
        ],
        "datasets": [
            {"name": "ds1", "description": None},
            {"name": "ds2", "description": None},
        ],
        # ds2 doesn't hold `trigger` -- a legitimate export could never
        # produce this pairing; this simulates a crafted/corrupted dump.
        "records": [
            {
                "dataset": "ds2",
                "schema": "child",
                "data": {},
                "parent_record_id": str(trigger.id),
            }
        ],
        "workflows": [],
        "plugins": [],
    }
    dump_file = project_dir / "malicious-dump.yaml"
    dump_file.write_text(yaml.dump(dump_doc, sort_keys=False))

    result = runner.invoke(app, ["restore", str(dump_file), "--yes"])

    assert result.exit_code == 0, result.output
    assert "Record skipped" in result.output
    assert "0/1" in result.output

    ctx = build_local_context(load_config())
    try:
        assert ctx.record_svc.find("ds2", schema_name="child", filters=[]) == []
    finally:
        ctx.close()


def test_dump_and_restore_keep_field_restrictions_and_name_templates(
    project_dir: Path, tmp_path_factory, monkeypatch
) -> None:
    """A dump once wrote only each field's name, label, type and required, so a
    restored reference field lost the schema it points at and the record form
    had nothing to search."""
    ctx = build_local_context(load_config())
    ctx.schema_svc.create("species")
    ctx.schema_svc.add_field("species", "common_name", "string")
    ctx.schema_svc.create("encounter")
    ctx.schema_svc.add_field(
        "encounter", "species", "reference", restrictions={"schema": "species"}
    )
    ctx.schema_svc.add_field(
        "encounter",
        "depth",
        "float",
        restrictions={"min": 0, "unit": "m"},
        default_value=1.5,
    )
    ctx.schema_svc.add_field(
        "encounter",
        "photo",
        "file",
        restrictions={"filename_template": "{depth}-{species}"},
    )
    ctx.schema_svc.update("encounter", display_template="{depth}")
    ctx.dataset_svc.create(
        "study", timezone="Europe/London", schemas=["species", "encounter"]
    )
    ctx.commit()
    ctx.close()

    dump_file = project_dir / "d.yaml"
    assert runner.invoke(app, ["dump", "-o", str(dump_file)]).exit_code == 0

    other = tmp_path_factory.mktemp("restored")
    monkeypatch.chdir(other)
    assert runner.invoke(app, ["init", "--sqlite", str(other)]).exit_code == 0
    result = runner.invoke(app, ["restore", str(dump_file), "--yes"])
    assert result.exit_code == 0, result.output

    ctx = build_local_context(load_config())
    try:
        fields = {f.name: f for f in ctx.schema_svc.get("encounter").fields}
        assert fields["species"].restrictions == {"schema": "species"}
        assert fields["depth"].restrictions == {"min": 0, "unit": "m"}
        assert fields["depth"].default_value == 1.5
        assert fields["photo"].restrictions == {
            "filename_template": "{depth}-{species}"
        }
        assert ctx.schema_svc.get("encounter").display_template == "{depth}"
        assert ctx.dataset_svc.get("study").timezone == "Europe/London"
    finally:
        ctx.close()
