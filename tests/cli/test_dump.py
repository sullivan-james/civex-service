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
