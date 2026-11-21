"""`civex record review` and `civex record note add|list|edit|resolve|delete|restore`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_records_are_marked_from_the_cli(
    project_dir: Path, ctx, make_schema, make_collection, make_record
):
    make_schema("sample", fields=[("site", "string")])
    make_collection("survey")
    one = make_record("survey", "sample", {"site": "a"})
    make_record("survey", "sample", {"site": "b"})

    by_id = runner.invoke(app, ["record", "review", "checked", "--id", str(one.id)])
    assert by_id.exit_code == 0, by_id.output
    assert "Marked 1 record(s) 'Checked'" in by_id.output

    all_of = runner.invoke(
        app, ["record", "review", "needs_check", "--in", "survey", "-s", "sample"]
    )
    assert all_of.exit_code == 0, all_of.output
    assert "Marked 2 record(s) 'Needs a check'" in all_of.output

    neither = runner.invoke(app, ["record", "review", "checked"])
    assert neither.exit_code == 1
    unknown = runner.invoke(app, ["record", "review", "looked", "--id", str(one.id)])
    assert unknown.exit_code == 1


def test_notes_from_the_cli(
    project_dir: Path, ctx, make_schema, make_collection, make_record
):
    make_schema("sample", fields=[("site", "string")])
    make_collection("survey")
    record = make_record("survey", "sample", {"site": "a"})
    rid = str(record.id)

    added = runner.invoke(app, ["record", "note", "add", rid, "depth looks off"])
    assert added.exit_code == 0, added.output
    note_id = added.output.split("Note ")[1].split()[0]

    listed = runner.invoke(app, ["record", "note", "list", rid])
    assert "depth looks off" in listed.output

    edited = runner.invoke(app, ["record", "note", "edit", note_id, "re-check it"])
    assert edited.exit_code == 0, edited.output
    resolved = runner.invoke(app, ["record", "note", "resolve", note_id])
    assert resolved.exit_code == 0, resolved.output
    still_open = runner.invoke(app, ["record", "note", "list", rid, "--open"])
    assert "No notes." in still_open.output

    deleted = runner.invoke(app, ["record", "note", "delete", note_id])
    assert deleted.exit_code == 0, deleted.output
    restored = runner.invoke(app, ["record", "note", "restore", note_id])
    assert restored.exit_code == 0, restored.output
    assert "re-check it" in runner.invoke(app, ["record", "note", "list", rid]).output
