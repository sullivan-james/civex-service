"""`civex record summarise`: the summary as a table, or as CSV."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def _seed(make_schema, make_collection, make_record) -> None:
    make_schema("sample", fields=[("habitat", "string"), ("depth", "float")])
    make_collection("survey")
    for habitat, depth in (("reef", 2.0), ("reef", 4.0), ("sand", 10.0)):
        make_record("survey", "sample", {"habitat": habitat, "depth": depth})


def _run(*args: str):
    return runner.invoke(
        app, ["record", "summarise", "--in", "survey", "-s", "sample", *args]
    )


def test_a_table_with_totals(
    project_dir: Path, ctx, make_schema, make_collection, make_record
) -> None:
    _seed(make_schema, make_collection, make_record)
    result = _run("--by", "habitat", "-m", "count", "-m", "mean:depth")
    assert result.exit_code == 0, result.output
    for text in ("Habitat", "Average Depth", "reef", "sand", "Total", "5.33333"):
        assert text in result.output


def test_csv_and_filters(
    project_dir: Path, ctx, make_schema, make_collection, make_record
) -> None:
    _seed(make_schema, make_collection, make_record)
    result = _run("--by", "depth:5", "-m", "count", "-w", "habitat=reef", "--csv")
    assert result.exit_code == 0, result.output
    assert list(csv.reader(io.StringIO(result.output))) == [
        ["Depth", "Records"],
        ["0 to under 5", "2"],
        ["Total", "2"],
    ]


def test_refusals(
    project_dir: Path, ctx, make_schema, make_collection, make_record
) -> None:
    _seed(make_schema, make_collection, make_record)
    result = _run("-m", "mean:habitat")
    assert result.exit_code == 1 and "mean" in result.output
    result = _run("--format", "xlsx")
    assert result.exit_code == 1
