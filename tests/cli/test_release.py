"""`civex release create|list|show|verify|withdraw|yank|export|correct|cite|diff|download`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_releases_from_the_cli(
    project_dir: Path, ctx, make_schema, make_collection, make_record, tmp_path
):
    make_schema("sample", fields=[("site", "string"), ("photo", "file")])
    make_collection("survey")
    photo = ctx.file_svc.store_bytes(b"a photo", "p.jpg")
    make_record("survey", "sample", {"site": "a", "photo": photo.to_dict()})
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
            "Ada Lovelace|0000-0002-1825-0097|Analytical Society",
            "-k",
            "seals",
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
    assert "0000-0002-1825-0097" in shown.output and "seals" in shown.output

    verified = runner.invoke(app, ["release", "verify", "v1"])
    assert verified.exit_code == 0 and "intact" in verified.output
    deep = runner.invoke(app, ["release", "verify", "v1", "--deep"])
    assert deep.exit_code == 0 and "1 read back" in deep.output, deep.output

    exported = runner.invoke(app, ["release", "export", "v1", "--mode", "copy"])
    assert exported.exit_code == 0, exported.output
    (made_at,) = (project_dir / "_civex" / "exports").iterdir()
    assert (made_at / "manifest-sha256.txt").read_text().startswith(photo.sha256)

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

    kept = runner.invoke(app, ["release", "yank", "v1", "-r", "consent"], input="n\n")
    assert kept.exit_code == 1 and "gives up 2 files" in kept.output
    yanked = runner.invoke(app, ["release", "yank", "v1", "-r", "consent", "--yes"])
    assert yanked.exit_code == 0 and "Yanked" in yanked.output
    assert "yanked" in runner.invoke(app, ["release", "list"]).output
