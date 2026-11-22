"""`civex record note add|reply|list|edit|resolve|delete|restore`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


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

    replied = runner.invoke(
        app, ["record", "note", "reply", note_id, "it was the sensor"]
    )
    assert replied.exit_code == 0, replied.output
    assert "Reply " in replied.output

    listed = runner.invoke(app, ["record", "note", "list", rid])
    assert "depth looks off" in listed.output
    # The reply is under the note it answers.
    lines = listed.output.splitlines()
    first = next(i for i, line in enumerate(lines) if "depth looks off" in line)
    reply = next(i for i, line in enumerate(lines) if "it was the sensor" in line)
    assert reply > first and "↳" in lines[reply]

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
