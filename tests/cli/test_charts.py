"""`civex schema charts list|add|remove|clear` and `civex dashboard
show|add|remove`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def _seed(make_schema, make_collection, make_record) -> None:
    make_schema(
        "sample", fields=[("habitat", "string"), ("depth", "float"), ("spot", "geo")]
    )
    make_collection("survey")
    for habitat, depth in (("reef", 2.0), ("reef", 4.0), ("sand", 10.0)):
        make_record("survey", "sample", {"habitat": habitat, "depth": depth})


def test_a_kinds_charts_are_added_listed_and_removed(
    project_dir: Path, ctx, make_schema, make_collection, make_record
):
    _seed(make_schema, make_collection, make_record)
    none = runner.invoke(app, ["schema", "charts", "list", "sample"])
    assert "has no charts" in none.output
    added = runner.invoke(
        app,
        ["schema", "charts", "add", "sample", "--by", "habitat", "-m", "mean:depth"],
    )
    assert added.exit_code == 0, added.output
    mapped = runner.invoke(
        app, ["schema", "charts", "add", "sample", "--map", "spot", "--title", "Where"]
    )
    assert mapped.exit_code == 0, mapped.output
    listed = runner.invoke(app, ["schema", "charts", "list", "sample"])
    assert "mean:depth by habitat" in listed.output
    assert "a map of spot" in listed.output and "Where" in listed.output

    first = listed.output.split()[0]
    removed = runner.invoke(app, ["schema", "charts", "remove", "sample", first])
    assert removed.exit_code == 0, removed.output
    assert (
        "mean:depth"
        not in runner.invoke(app, ["schema", "charts", "list", "sample"]).output
    )
    assert runner.invoke(app, ["schema", "charts", "clear", "sample"]).exit_code == 0
    assert (
        "has no charts"
        in runner.invoke(app, ["schema", "charts", "list", "sample"]).output
    )


def test_a_chart_is_put_on_the_page(
    project_dir: Path, ctx, make_schema, make_collection, make_record
):
    _seed(make_schema, make_collection, make_record)
    added = runner.invoke(
        app,
        [
            "dashboard", "add", "--schema", "sample", "--by", "habitat",
            "--in", "survey", "--size", "wide",
        ],
    )  # fmt: skip
    assert added.exit_code == 0, added.output
    assert "chart: sample in survey: count by habitat" in " ".join(added.output.split())

    removed = runner.invoke(app, ["dashboard", "remove", "widget-storage"])
    assert removed.exit_code == 0, removed.output
    listed = runner.invoke(app, ["dashboard", "show"])
    assert "widget-storage" not in listed.output
    assert "widget-triggers" in listed.output


def test_bad_choices_are_refused(
    project_dir: Path, ctx, make_schema, make_collection, make_record
):
    _seed(make_schema, make_collection, make_record)
    for args in (
        ["schema", "charts", "add", "sample", "--by", "nowhere"],
        ["schema", "charts", "remove", "sample", "nothing"],
        ["dashboard", "add", "--schema", "sample", "--by", "nowhere"],
        ["dashboard", "add", "--widget", "weather"],
        ["dashboard", "remove", "nothing"],
    ):
        assert runner.invoke(app, args).exit_code == 1, args
