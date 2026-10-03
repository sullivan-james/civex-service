from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.config import load_config
from civex.context import build_local_context
from civex.main import app

runner = CliRunner()


def _plain(result) -> str:
    return " ".join(result.output.split())


def _two_volumes(tmp_path: Path, files: int = 4) -> None:
    for name in ("a", "b"):
        path = tmp_path / name
        path.mkdir()
        assert (
            runner.invoke(app, ["store", "add", name, "--path", str(path)]).exit_code
            == 0
        )
    ctx = build_local_context(load_config())
    ctx.store_svc.set_queue(["a"])
    for i in range(files):
        ctx.file_svc._store.put(f"file {i} ".encode() * 40, f"f{i}.txt")
    ctx.commit()
    ctx.close()


def test_dry_run_shows_the_plan_and_moves_nothing(
    project_dir: Path, tmp_path: Path
) -> None:
    _two_volumes(tmp_path)
    result = runner.invoke(
        app, ["store", "move", "--off", "a", "--to", "b", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "Would move 4 files" in _plain(result)
    assert runner.invoke(app, ["store", "transfers", "list"]).output.count("drain") == 0


def test_move_drains_a_volume_and_is_listed(project_dir: Path, tmp_path: Path) -> None:
    _two_volumes(tmp_path)
    result = runner.invoke(app, ["store", "move", "--off", "a", "--to", "b"])
    assert result.exit_code == 0, result.output
    assert "completed" in _plain(result)
    listing = _plain(runner.invoke(app, ["store", "transfers", "list"]))
    assert "drain" in listing and "4/4 files" in listing


def test_move_needs_exactly_one_of_off_or_collection(project_dir: Path) -> None:
    assert runner.invoke(app, ["store", "move", "--to", "b"]).exit_code == 2


def test_an_impossible_move_is_refused_with_reasons(
    project_dir: Path, tmp_path: Path
) -> None:
    _two_volumes(tmp_path)
    result = runner.invoke(app, ["store", "move", "--off", "a", "--to", "a"])
    assert result.exit_code == 1


def test_set_state(project_dir: Path, tmp_path: Path) -> None:
    _two_volumes(tmp_path)
    assert runner.invoke(app, ["store", "set-state", "a", "readonly"]).exit_code == 0
    assert "read-only" in _plain(runner.invoke(app, ["store", "list"]))


def test_collections_shows_where_each_collections_files_are(
    project_dir: Path, tmp_path: Path
) -> None:
    _two_volumes(tmp_path, files=0)
    ctx = build_local_context(load_config())
    ctx.schema_svc.create("doc")
    ctx.schema_svc.add_field("doc", "scan", "file")
    ctx.dataset_svc.create("study")
    store = ctx.file_svc._store
    for vol, data in (("a", b"x" * 100), ("b", b"y" * 300)):
        ctx.store_svc.set_queue([vol])
        ref = store.put(data, f"{vol}.bin")
        ctx.record_svc.add("study", "doc", {"scan": ref.to_dict()})
    ctx.commit()
    ctx.close()

    out = _plain(runner.invoke(app, ["store", "collections"]))

    assert "study 2 files" in out
    assert "a: 1 files" in out and "b: 1 files" in out
    assert _plain(runner.invoke(app, ["store", "collections", "study"])) == out
    assert "No collection has files" not in out
