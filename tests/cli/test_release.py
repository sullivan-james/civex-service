"""`civex release list|show|verify|export|files|cite|diff|download`: releases are
published on a hub, so the ones already on this computer are read-only."""

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

    # Releases are made on a hub; one already here (made by an older civex, or
    # through the service) stays readable.
    ctx.release_svc.create(
        "v1",
        "Survey",
        authors=[{"name": "Ada Lovelace", "orcid": "0000-0002-1825-0097"}],
        keywords=["seals"],
        doi="10.1234/x",
    )
    ctx.commit()

    listed = runner.invoke(app, ["release", "list"])
    assert listed.exit_code == 0 and "v1" in listed.output
    shown = runner.invoke(app, ["release", "show", "v1"])
    assert shown.exit_code == 0 and "sha256:" in shown.output
    assert "0000-0002-1825-0097" in shown.output and "seals" in shown.output

    verified = runner.invoke(app, ["release", "verify", "v1"])
    assert verified.exit_code == 0 and "intact" in verified.output
    deep = runner.invoke(app, ["release", "verify", "v1", "--deep"])
    assert deep.exit_code == 0 and "1 read back" in deep.output, deep.output

    exported = runner.invoke(app, ["release", "files", "v1", "--mode", "copy"])
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
    added = make_record("survey", "sample", {"site": "b"})
    ctx.commit()
    since = runner.invoke(app, ["release", "diff", "v1"])
    assert since.exit_code == 0 and "survey" in since.output, since.output
    assert "1 of its 1 records are unchanged" in since.output
    shown = runner.invoke(app, ["release", "diff", "v1", "--show", "added"])
    assert str(added.id) in shown.output

    # The commands that made or changed a release are gone.
    for gone in ("create", "correct", "withdraw", "yank"):
        answer = runner.invoke(app, ["release", gone, "v1"])
        assert answer.exit_code == 2, (gone, answer.output)
    assert "yanked" not in runner.invoke(app, ["release", "list"]).output


def test_civex_release_says_where_releases_are_published():
    bare = runner.invoke(app, ["release"])
    assert bare.exit_code == 0
    assert "published on a civex hub" in bare.output.replace("\n", " ")
    assert "release list" in bare.output


def test_a_release_here_is_exported_as_one_bundle_with_its_files(
    project_dir: Path, ctx, make_schema, make_collection, make_record, tmp_path
):
    import json
    import zipfile

    make_schema("sample", fields=[("site", "string"), ("photo", "file")])
    make_collection("survey")
    photo = ctx.file_svc.store_bytes(b"a photo", "p.jpg")
    make_record("survey", "sample", {"site": "a", "photo": photo.to_dict()})
    ctx.release_svc.create("v1", "Survey")
    ctx.commit()
    out = tmp_path / "v1.civex.zip"
    done = runner.invoke(app, ["release", "export", "v1", "-o", str(out)])
    assert done.exit_code == 0, done.output
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("bundle.json"))
        assert f"files/{photo.sha256}" in zf.namelist()
    assert manifest["files"]["included"] and manifest["files"]["count"] == 1
    assert manifest["files"]["missing"] == []
