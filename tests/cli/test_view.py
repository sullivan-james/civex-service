from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

from typer.testing import CliRunner

from civex.config import load_config
from civex.context import AppContext, build_local_context
from civex.main import app

runner = CliRunner()


def test_view_export_csv_writes_file(project_dir: Path) -> None:
    ctx: AppContext = build_local_context(load_config())
    ctx.schema_svc.create("trial")
    ctx.schema_svc.add_field("trial", "subject", "string")
    ctx.dataset_svc.create("study")
    ctx.record_svc.add("study", "trial", {"subject": "S01"})
    ctx.commit()
    ctx.view_svc.create("trial", "all", columns=["subject"])
    ctx.commit()
    ctx.close()

    result = runner.invoke(app, ["view", "export", "trial", "all"])
    assert result.exit_code == 0, result.output

    dest = project_dir / "all.csv"
    assert dest.exists()
    rows = list(csv.DictReader(dest.open()))
    assert rows == [{"subject": "S01"}]


def test_view_export_json_to_custom_output(project_dir: Path) -> None:
    ctx: AppContext = build_local_context(load_config())
    ctx.schema_svc.create("trial")
    ctx.schema_svc.add_field("trial", "subject", "string")
    ctx.dataset_svc.create("study")
    ctx.record_svc.add("study", "trial", {"subject": "S01"})
    ctx.commit()
    ctx.view_svc.create("trial", "all", columns=["subject"])
    ctx.commit()
    ctx.close()

    dest = project_dir / "out.json"
    result = runner.invoke(
        app,
        [
            "view",
            "export",
            "trial",
            "all",
            "--format",
            "json",
            "--output",
            str(dest),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(dest.read_text()) == [{"subject": "S01"}]


def test_view_export_bundles_file_columns_as_zip(project_dir: Path) -> None:
    ctx: AppContext = build_local_context(load_config())
    ctx.schema_svc.create("invoice")
    ctx.schema_svc.add_field("invoice", "scan", "file")
    ctx.dataset_svc.create("study")
    ref = ctx.file_svc.store_bytes(b"scan-bytes", "scan.pdf")
    ctx.record_svc.add("study", "invoice", {"scan": ref.to_dict()})
    ctx.commit()
    ctx.view_svc.create("invoice", "with_scan", columns=["scan"])
    ctx.commit()
    ctx.close()

    result = runner.invoke(app, ["view", "export", "invoice", "with_scan"])
    assert result.exit_code == 0, result.output

    dest = project_dir / "with_scan.zip"
    assert dest.exists()
    zf = zipfile.ZipFile(dest)
    names = zf.namelist()
    assert "with_scan.csv" in names
    file_entries = [n for n in names if n != "with_scan.csv"]
    assert len(file_entries) == 1
    assert zf.read(file_entries[0]) == b"scan-bytes"


def test_view_export_missing_view_exits_nonzero(project_dir: Path) -> None:
    ctx: AppContext = build_local_context(load_config())
    ctx.schema_svc.create("trial")
    ctx.commit()
    ctx.close()

    result = runner.invoke(app, ["view", "export", "trial", "missing"])
    assert result.exit_code != 0


def test_view_export_invalid_format_exits_nonzero(project_dir: Path) -> None:
    ctx: AppContext = build_local_context(load_config())
    ctx.schema_svc.create("trial")
    ctx.commit()
    ctx.view_svc.create("trial", "all")
    ctx.commit()
    ctx.close()

    result = runner.invoke(app, ["view", "export", "trial", "all", "--format", "xml"])
    assert result.exit_code != 0
