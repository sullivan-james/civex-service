"""Opening a project made by a released civex: it migrates, keeps its data and
history, its history converts to deltas reading the same, and replaying it
still gives what is in the database.

The databases in tests/fixtures/upgrades were made by those releases' own code
(a project with a child schema, edits, a field rename, a delete and a restore);
tests/fixtures/upgrades/make_fixture.py makes another."""

from __future__ import annotations

import gzip
import time
from pathlib import Path

import pytest

from civex.config import load_config
from civex.context import build_local_context
from civex.project import scaffold_project

# Made with each release's own code by tests/fixtures/upgrades/make_fixture.py
# (its docstring says how); add one for each release.
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "upgrades"


@pytest.fixture(params=["1.1.4", "1.2.0"])
def released(request, tmp_path, monkeypatch):
    """A project folder holding the database a release made, not yet opened."""
    root = tmp_path / f"from-{request.param}"
    scaffold_project(root, db_url=f"sqlite:///{(root / 'civex.db').as_posix()}")
    with gzip.open(_FIXTURES / f"civex-{request.param}.db.gz") as src:
        (root / "civex.db").write_bytes(src.read())
    monkeypatch.chdir(root)
    return request.param


def _open():
    return build_local_context(load_config())


def test_a_released_project_opens_quickly_and_keeps_everything(released):
    started = time.monotonic()
    ctx = _open()
    opened = time.monotonic() - started
    try:
        assert opened < 15, f"opening took {opened:.1f}s"  # structure only
        site = ctx.schema_svc.get("site")
        assert "remarks" in [f.name for f in site.fields]  # the rename held
        assert len(ctx.record_svc.find("survey", "site", limit=100)) == 19
        assert len(ctx.history_svc.page(limit=500)) >= 117
    finally:
        ctx.close()


def test_its_history_converts_to_deltas_and_reads_the_same(released):
    ctx = _open()
    try:
        before = {
            e.id: (e.action, e.entity_type, e.changes)
            for e in ctx.history_svc.page(limit=500)
        }
        whole = ctx.compaction_svc.remaining()
        assert whole > 50
        while ctx.compaction_svc.step(40).remaining:
            ctx.commit()
        ctx.commit()
        after = {
            e.id: (e.action, e.entity_type, e.changes)
            for e in ctx.history_svc.page(limit=500)
        }
        assert after == before
        assert ctx.compaction_svc.remaining() == 0
    finally:
        ctx.close()


def test_replaying_its_history_still_gives_the_database(released):
    """From 1.2.0 on, history stores values by field id and every attribute a
    thing has, so replaying it rebuilds the database. 1.1.4's history keys
    record values by field name and predates unique keys and schema lists: it
    is read as it is (Activity shows it), but can't be replayed. Sync never
    replays history from before a project syncs (it sends the state)."""
    if released == "1.1.4":
        pytest.skip("1.1.4's history predates field ids and later attributes")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "audit_replay",
        Path(__file__).resolve().parents[1] / "services" / "test_audit_replay.py",
    )
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    _wrong = replay._wrong

    ctx = _open()
    try:
        while ctx.compaction_svc.step(100).remaining:
            ctx.commit()
        ctx.commit()
        assert _wrong(ctx) == []
    finally:
        ctx.close()
