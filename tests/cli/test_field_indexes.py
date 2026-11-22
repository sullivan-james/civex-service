"""`civex schema index` and `civex db indexes`: choosing a field index and
keeping the database in step from the command line."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.config import load_config
from civex.context import build_local_context
from civex.main import app

runner = CliRunner()


def _schema() -> None:
    ctx = build_local_context(load_config())
    ctx.schema_svc.create("sample")
    ctx.schema_svc.add_field("sample", "depth", "float")
    ctx.schema_svc.add_field("sample", "code", "string")
    ctx.commit()
    ctx.close()


def test_index_a_field_and_take_it_back(project_dir: Path, background_upkeep) -> None:
    _schema()
    result = runner.invoke(app, ["schema", "index", "sample", "depth"])
    assert result.exit_code == 0, result.output
    assert "'depth' is indexed (chosen)" in result.output
    # Never built while the command runs: a process of its own does it.
    assert "in the background" in result.output
    assert background_upkeep == [project_dir]
    listed = runner.invoke(app, ["db", "indexes"])
    assert "depth" in listed.output and "not yet" in listed.output

    # The way to do it here and now (what the background process runs).
    built = runner.invoke(app, ["db", "indexes", "--reconcile"])
    assert built.exit_code == 0, built.output
    assert "Built 1 index" in built.output
    listed = runner.invoke(app, ["db", "indexes"])
    assert listed.exit_code == 0, listed.output
    assert "depth" in listed.output and "yes" in listed.output

    result = runner.invoke(app, ["schema", "index", "sample", "depth", "--off"])
    assert result.exit_code == 0, result.output
    assert "no longer indexed" in result.output
    assert len(background_upkeep) == 2
    assert (
        "Dropped 1 index" in runner.invoke(app, ["db", "indexes", "--reconcile"]).output
    )
    assert "No field indexes." in runner.invoke(app, ["db", "indexes"]).output


def test_the_background_process_logs_one_line(project_dir: Path) -> None:
    _schema()
    runner.invoke(app, ["schema", "index", "sample", "depth"])
    result = runner.invoke(app, ["db", "indexes", "--reconcile", "--background"])
    assert result.exit_code == 0, result.output
    assert "field indexes: 1 built, 0 dropped" in result.output
    assert "Schema" not in result.output  # no table: it is a log


def test_a_uniqueness_key_is_indexed_and_unindexable_fields_are_refused(
    project_dir: Path,
) -> None:
    _schema()
    result = runner.invoke(app, ["schema", "add-unique", "sample", "code"])
    assert result.exit_code == 0, result.output
    assert "in the background" in result.output
    listed = runner.invoke(app, ["db", "indexes", "--reconcile"])
    assert "Built 1 index" in listed.output
    assert "unique key" in listed.output

    ctx = build_local_context(load_config())
    ctx.schema_svc.add_field("sample", "photo", "file")
    ctx.commit()
    ctx.close()
    result = runner.invoke(app, ["schema", "index", "sample", "photo"])
    assert result.exit_code == 1
    assert "can't be indexed" in result.output
