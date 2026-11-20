"""`civex view save-analysis|show` and `civex dashboard show|add|remove`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def _seed(make_schema, make_collection, make_record) -> None:
    make_schema("sample", fields=[("habitat", "string"), ("depth", "float")])
    make_collection("survey")
    for habitat, depth in (("reef", 2.0), ("reef", 4.0), ("sand", 10.0)):
        make_record("survey", "sample", {"habitat": habitat, "depth": depth})


def test_an_analysis_is_saved_shown_and_put_on_the_page(
    project_dir: Path, ctx, make_schema, make_collection, make_record
):
    _seed(make_schema, make_collection, make_record)
    saved = runner.invoke(
        app,
        [
            "view",
            "save-analysis",
            "sample",
            "by habitat",
            "--summary-by",
            "habitat",
            "--summary-measure",
            "mean:depth",
            "--in",
            "survey",
        ],
    )
    assert saved.exit_code == 0, saved.output
    assert "Saved the analysis" in saved.output

    shown = runner.invoke(app, ["view", "show", "sample", "by habitat"])
    assert shown.exit_code == 0, shown.output
    assert "A saved analysis" in shown.output
    assert "reef" in shown.output and "sand" in shown.output

    again = runner.invoke(
        app, ["view", "save-analysis", "sample", "by habitat", "--by", "habitat"]
    )
    assert "Updated" in again.output

    added = runner.invoke(
        app, ["dashboard", "add", "--analysis", "sample/by habitat", "--size", "wide"]
    )
    assert added.exit_code == 0, added.output
    assert "analysis: sample/by habitat" in added.output

    removed = runner.invoke(app, ["dashboard", "remove", "widget-storage"])
    assert removed.exit_code == 0, removed.output
    listed = runner.invoke(app, ["dashboard", "show"])
    assert "widget-storage" not in listed.output
    assert "widget-triggers" in listed.output


def test_bad_choices_are_refused(
    project_dir: Path, ctx, make_schema, make_collection, make_record
):
    _seed(make_schema, make_collection, make_record)
    bad = runner.invoke(
        app, ["view", "save-analysis", "sample", "x", "--by", "nowhere"]
    )
    assert bad.exit_code == 1
    assert (
        runner.invoke(app, ["dashboard", "add", "--widget", "weather"]).exit_code == 1
    )
    assert runner.invoke(app, ["dashboard", "remove", "nothing"]).exit_code == 1
