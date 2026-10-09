"""Moving a project to another database: the flow around the copy -- picking a
target, refusing a non-empty one, switching config only after a verified copy,
history, and undo. (The copy itself is tested in tests/db/test_move.py.)"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from civex.config import load_config
from civex.context import AppContext
from civex.db import move as engine_move
from civex.db.sqlite_url import sqlite_url
from civex.domain.exceptions import ValidationError
from civex.services import db_move_service as svc
from civex.services import db_service


@pytest.fixture()
def project(ctx: AppContext, make_schema, make_collection, project_dir: Path):
    make_schema("patient", fields=[("name", "string")])
    make_collection("study")
    for i in range(12):
        ctx.record_svc.add("study", "patient", {"name": f"p{i}"})
    ctx.commit()
    return project_dir


def _target(tmp_path: Path, name: str = "moved.db") -> svc.TargetSpec:
    return svc.TargetSpec(kind="sqlite", path=str(tmp_path / name))


def test_a_move_copies_switches_and_records_itself(project: Path, tmp_path: Path):
    config = load_config()
    old_url = config.db.url
    old_file = Path(old_url.removeprefix("sqlite:///"))
    old_size = old_file.stat().st_size

    record = svc.run_move(config, _target(tmp_path))

    assert record.status == "done", record.error
    assert record.counts["records"] == 12
    assert load_config().db.url == sqlite_url(tmp_path / "moved.db")
    assert (tmp_path / "moved.db").exists()
    assert old_file.stat().st_size == old_size  # the original is never touched
    assert [m.id for m in svc.list_moves(load_config())] == [record.id]
    shown = svc.public(record)
    assert "from_url" not in shown and "to_url" not in shown


def test_preflight_describes_a_move_without_doing_anything(
    project: Path, tmp_path: Path
):
    config = load_config()
    before = config.db.url

    check = svc.preflight(config, _target(tmp_path))

    assert check.can_proceed and check.problems == []
    assert check.source.records == 12 and check.source.size_bytes
    assert check.target.rows == 0
    assert check.target_label == "SQLite file"
    assert not (tmp_path / "moved.db").exists()
    assert load_config().db.url == before
    assert svc.list_moves(config) == []


def test_a_target_that_already_has_data_is_refused(project: Path, tmp_path: Path):
    svc.run_move(load_config(), _target(tmp_path, "first.db"))
    # Now using first.db; try to move into the database we just left (full).
    config = load_config()
    old = Path(svc.list_moves(config)[0].from_url.removeprefix("sqlite:///"))

    check = svc.preflight(
        config, svc.TargetSpec(kind="postgres", url=f"sqlite:///{old}")
    )
    assert not check.can_proceed
    assert "isn't empty" in check.problems[0]
    with pytest.raises(ValidationError, match="isn't empty"):
        svc.run_move(config, svc.TargetSpec(kind="postgres", url=f"sqlite:///{old}"))
    assert load_config().db.url == sqlite_url(tmp_path / "first.db")


def test_moving_to_the_database_in_use_is_refused(project: Path):
    config = load_config()
    with pytest.raises(ValidationError, match="already in use"):
        svc.run_move(config, svc.TargetSpec(kind="postgres", url=config.db.url))


def test_a_failed_copy_changes_nothing(project: Path, tmp_path: Path, monkeypatch):
    config = load_config()
    before = config.db.url

    def boom(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(engine_move, "copy_database", boom)
    record = svc.run_move(config, _target(tmp_path))

    assert record.status == "failed" and "disk full" in (record.error or "")
    assert load_config().db.url == before
    assert not (tmp_path / "moved.db").exists()  # no litter
    assert svc.list_moves(load_config())[0].status == "failed"


def test_a_copy_that_does_not_verify_is_not_switched_to(
    project: Path, tmp_path: Path, monkeypatch
):
    config = load_config()
    before = config.db.url
    monkeypatch.setattr(
        engine_move,
        "copy_database",
        lambda *a, **kw: engine_move.CopyResult(
            counts={},
            seconds=0.1,
            problems=["records: 12 rows in the original, 11 in the copy"],
        ),
    )

    record = svc.run_move(config, _target(tmp_path))

    assert record.status == "failed"
    assert record.problems and "nothing was switched" in (record.error or "")
    assert load_config().db.url == before


def test_cancelling_leaves_everything_as_it_was(project: Path, tmp_path: Path):
    config = load_config()
    before = config.db.url
    cancel = threading.Event()
    cancel.set()

    record = svc.run_move(config, _target(tmp_path), cancel=cancel)

    assert record.status == "cancelled"
    assert load_config().db.url == before
    assert not (tmp_path / "moved.db").exists()


def test_progress_reaches_the_caller(project: Path, tmp_path: Path):
    seen: list[engine_move.Progress] = []
    svc.run_move(
        load_config(),
        _target(tmp_path),
        progress=lambda p: seen.append(engine_move.Progress(**p.__dict__)),
    )
    assert {"copy", "verify", "finalize"} <= {p.phase for p in seen}


def test_revert_points_back_at_the_original(project: Path, tmp_path: Path):
    config = load_config()
    original = config.db.url
    record = svc.run_move(config, _target(tmp_path))

    reverted = svc.revert(load_config(), record.id)

    assert load_config().db.url == original
    assert reverted.reverted_at
    with pytest.raises(ValidationError, match="already reverted"):
        svc.revert(load_config(), record.id)


def test_revert_refuses_when_the_project_has_moved_on(project: Path, tmp_path: Path):
    first = svc.run_move(load_config(), _target(tmp_path, "a.db"))
    svc.run_move(load_config(), _target(tmp_path, "b.db"))

    with pytest.raises(ValidationError, match="no longer uses"):
        svc.revert(load_config(), first.id)


def test_only_one_move_runs_at_a_time(project: Path, tmp_path: Path):
    assert svc._active.acquire(blocking=False)
    try:
        with pytest.raises(ValidationError, match="already running"):
            svc.run_move(load_config(), _target(tmp_path))
    finally:
        svc._active.release()


def test_switching_to_an_empty_database_is_refused_while_data_would_be_left_behind(
    project: Path, tmp_path: Path
):
    """The failure that prompted all this: pointing a project at a fresh,
    empty database used to make its data silently vanish from the UI."""
    config = load_config()
    empty = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{empty}")
    from civex.db.migrate import ensure_schema_current

    ensure_schema_current(engine)
    engine.dispose()

    with pytest.raises(ValidationError, match="12 records"):
        db_service.set_url(config, f"sqlite:///{empty}")
    assert load_config().db.url != f"sqlite:///{empty}"


def test_switching_is_allowed_when_nothing_would_be_left_behind(
    project: Path, tmp_path: Path
):
    # The destination has data of its own: that's "use an existing database".
    svc.run_move(load_config(), _target(tmp_path, "full.db"))
    config = load_config()
    full = config.db.url
    original = svc.list_moves(config)[0].from_url
    db_service.set_url(config, original)  # original is full too -> allowed
    assert load_config().db.url == original
    assert full != original


def test_postgres_url_is_built_and_escaped_from_fields():
    if db_service.detect_pg_driver() is None:
        pytest.skip("no PostgreSQL driver installed")
    url = svc.postgres_url(
        svc.TargetSpec(
            kind="postgres",
            host="db.example.org",
            port=5433,
            database="my db",
            user="ada",
            password="p@ss:w/rd",
        )
    )
    assert url.endswith("@db.example.org:5433/my%20db")
    assert "p%40ss%3Aw%2Frd" in url
    with pytest.raises(ValidationError, match="host and a database"):
        svc.postgres_url(svc.TargetSpec(kind="postgres"))


def test_a_move_keeps_which_copy_each_record_uses(
    ctx: AppContext, make_schema, make_collection, project_dir: Path, tmp_path: Path
):
    """`file_references.volume` (the copy each record's file points at) is
    local data like the inventory: moving the database carries it, so no
    record's file changes drive by being moved to another database."""
    make_schema("scan", fields=[("image", "file")])
    make_collection("study")
    ref = ctx.file_svc.store_bytes(b"pixels", "a.png")
    record = ctx.record_svc.add("study", "scan", {"image": ref.to_dict()})
    ctx.commit()
    before = ctx.file_svc._store.copies_used([record.id])
    assert before == {(record.id, ref.sha256): "default"}
    ctx.close()

    done = svc.run_move(load_config(), _target(tmp_path))

    assert done.status == "done", done.error
    moved = create_engine(sqlite_url(tmp_path / "moved.db"))
    with moved.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT sha256, volume FROM file_references WHERE record_id IS NOT NULL"
        ).all()
    moved.dispose()
    assert rows == [(ref.sha256, "default")]
