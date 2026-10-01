"""`civex db move`, `moves` and `revert`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from civex.config import load_config
from civex.context import AppContext
from civex.main import app

runner = CliRunner()


@pytest.fixture()
def project(ctx: AppContext, make_schema, make_collection, project_dir: Path):
    make_schema("patient", fields=[("name", "string")])
    make_collection("study")
    for i in range(6):
        ctx.record_svc.add("study", "patient", {"name": f"p{i}"})
    ctx.commit()
    return project_dir


def test_move_to_a_new_sqlite_file_then_revert(project: Path, tmp_path: Path):
    original = load_config().db.url
    target = tmp_path / "moved.db"

    moved = runner.invoke(
        app, ["db", "move", "--to", "sqlite", "--path", str(target), "--yes"]
    )

    assert moved.exit_code == 0, moved.output
    assert "6 records" in moved.output and "Moved" in moved.output
    assert load_config().db.url == f"sqlite:///{target}"

    listed = runner.invoke(app, ["db", "moves"])
    assert "done" in listed.output
    move_id = json.loads((project / "_civex" / "db-moves.json").read_text())[0]["id"]

    back = runner.invoke(app, ["db", "revert", move_id, "--yes"])
    assert back.exit_code == 0, back.output
    assert load_config().db.url == original


def test_move_json_prints_the_outcome_without_prompts(project: Path, tmp_path: Path):
    result = runner.invoke(
        app,
        ["db", "move", "--to", "sqlite", "--path", str(tmp_path / "j.db"), "--json"],
    )

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["status"] == "done" and body["counts"]["records"] == 6
    assert "from_url" not in body


def test_move_asks_before_doing_anything_and_declining_changes_nothing(
    project: Path, tmp_path: Path
):
    before = load_config().db.url
    target = tmp_path / "no.db"

    result = runner.invoke(
        app, ["db", "move", "--to", "sqlite", "--path", str(target)], input="n\n"
    )

    assert result.exit_code != 0
    assert "From" in result.output and "To" in result.output
    assert load_config().db.url == before and not target.exists()


def test_move_refuses_a_destination_that_has_data(project: Path, tmp_path: Path):
    runner.invoke(
        app, ["db", "move", "--to", "sqlite", "--path", str(tmp_path / "a.db"), "--yes"]
    )
    full = json.loads((project / "_civex" / "db-moves.json").read_text())[0]["from_url"]

    result = runner.invoke(
        app, ["db", "move", "--to", "postgres", "--url", full, "--yes"]
    )

    assert result.exit_code == 1
    assert "isn't empty" in result.output


def test_move_needs_a_destination_when_non_interactive(project: Path):
    result = runner.invoke(app, ["db", "move", "--json"])
    assert result.exit_code == 2


def test_setup_docker_no_longer_claims_to_move_data():
    out = runner.invoke(app, ["db", "setup-docker", "--help"]).output
    assert "db move" in out
