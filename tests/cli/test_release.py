"""`civex release create|list|show|verify|withdraw|correct|cite|diff|download`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_releases_from_the_cli(
    project_dir: Path, ctx, make_schema, make_collection, make_record, tmp_path
):
    make_schema("sample", fields=[("site", "string")])
    make_collection("survey")
    make_record("survey", "sample", {"site": "a"})
    ctx.commit()

    dry = runner.invoke(app, ["release", "create", "v1", "-t", "Survey", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "would hold" in dry.output

    made = runner.invoke(
        app,
        [
            "release",
            "create",
            "v1",
            "-t",
            "Survey",
            "-a",
            "Ada Lovelace",
            "--doi",
            "10.1234/x",
        ],
    )
    assert made.exit_code == 0, made.output
    assert "Made release v1" in made.output

    listed = runner.invoke(app, ["release", "list"])
    assert listed.exit_code == 0 and "v1" in listed.output
    shown = runner.invoke(app, ["release", "show", "v1"])
    assert shown.exit_code == 0 and "sha256:" in shown.output

    verified = runner.invoke(app, ["release", "verify", "v1"])
    assert verified.exit_code == 0 and "intact" in verified.output

    cited = runner.invoke(app, ["release", "cite", "v1", "-f", "bibtex"])
    assert cited.exit_code == 0 and cited.output.startswith("@misc{")

    out = tmp_path / "v1.zip"
    downloaded = runner.invoke(app, ["release", "download", "v1", "-o", str(out)])
    assert downloaded.exit_code == 0, downloaded.output
    assert out.read_bytes()[:2] == b"PK"

    unchanged = runner.invoke(app, ["release", "diff", "v1"])
    assert "Nothing has changed" in unchanged.output

    fixed = runner.invoke(app, ["release", "correct", "v1", "-t", "The survey"])
    assert fixed.exit_code == 0 and "The survey" in fixed.output

    refused = runner.invoke(app, ["release", "withdraw", "v1", "-r", ""])
    assert refused.exit_code == 1
    gone = runner.invoke(app, ["release", "withdraw", "v1", "-r", "wrong units"])
    assert gone.exit_code == 0 and "Withdrew" in gone.output

    taken = runner.invoke(app, ["release", "create", "v1", "-t", "Again"])
    assert taken.exit_code == 1
