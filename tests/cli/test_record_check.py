"""`civex record check`: what needs a look, and the records with one issue;
`civex schema update-field` warns before a rule leaves records behind."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def _seed(ctx, make_schema, make_collection, make_record) -> list[str]:
    make_schema("sample", fields=[("code", "string")])
    ctx.schema_svc.add_field("sample", "depth", "integer")
    ctx.commit()
    make_collection("survey")
    return [
        str(make_record("survey", "sample", {"code": f"s{d}", "depth": d}).id)
        for d in (10, 40, 80)
    ]


def test_tightening_warns_then_check_lists(
    project_dir: Path, ctx, make_schema, make_collection, make_record
) -> None:
    ids = _seed(ctx, make_schema, make_collection, make_record)
    # Declined: nothing changes.
    result = runner.invoke(
        app, ["schema", "update-field", "sample", "depth", "--max", "30"], input="n\n"
    )
    assert result.exit_code == 1
    assert "2 record(s) hold a value these rules refuse" in result.output
    result = runner.invoke(
        app, ["schema", "update-field", "sample", "depth", "--max", "30"], input="y\n"
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["record", "check", "--in", "survey", "-s", "sample"])
    assert result.exit_code == 0, result.output
    assert "Breaks a rule" in result.output
    assert "2 of 3 record(s)" in result.output

    result = runner.invoke(
        app,
        ["record", "check", "--in", "survey", "--issue", "breaks_rule", "-f", "depth"],
    )
    assert result.exit_code == 0, result.output
    assert ids[1] in result.output and ids[2] in result.output
    assert ids[0] not in result.output


def test_nothing_to_look_at_and_a_bad_issue(
    project_dir: Path, ctx, make_schema, make_collection, make_record
) -> None:
    _seed(ctx, make_schema, make_collection, make_record)
    result = runner.invoke(app, ["record", "check", "--in", "survey"])
    assert result.exit_code == 0, result.output
    assert "Nothing to look at in 3 record(s)" in result.output
    result = runner.invoke(app, ["record", "check", "--issue", "outlier"])
    assert result.exit_code == 1
