"""Field indexes are built in the background and, on SQLite, give way to
saves (`db/index_gate.py`): a build holds the write lock for as long as it
reads the kind's records, so a save that comes along interrupts it, and it is
started again once nobody has saved for a while. The timings that make this
matter (a minute per index at a million records) are in the PR, measured; these
tests hold the mechanism."""

from __future__ import annotations

import os
import time

import pytest
from sqlalchemy import text

from civex.db import index_gate
from civex.domain.field_index import (
    FieldIndexSpec,
    IndexBuildYielded,
    IndexProgress,
    kind_of,
)
from civex.services import index_jobs as jobs
from civex.services import index_service


@pytest.fixture()
def sample(ctx, make_schema, make_collection):
    make_schema("sample", fields=[("depth", "float"), ("code", "string")])
    make_collection("study")
    for i in range(50):
        ctx.record_svc.add("study", "sample", {"depth": float(i)}, with_labels=False)
    ctx.commit()
    schema = ctx.schema_svc.get("sample")
    f = next(f for f in schema.fields if f.name == "depth")
    return FieldIndexSpec(f.id, f.schema_id, kind_of(f.dtype) or "text")


def _engine(ctx):
    return ctx.index_svc._repo._s.get_bind()


def _db(ctx) -> str:
    return _engine(ctx).url.database


def test_saves_ask_for_their_turn_only_while_indexes_are_kept(ctx, sample):
    db = _db(ctx)
    wait = db + "-indexing.wait"
    with _engine(ctx).begin() as conn:
        conn.execute(text("UPDATE records SET updated_at = updated_at"))
    assert not os.path.exists(wait)  # nothing being built: a save costs a stat

    with ctx.index_svc._repo.upkeep():
        assert os.path.exists(db + "-indexing")
        with _engine(ctx).begin() as conn:
            conn.execute(text("SELECT count(*) FROM records"))
        assert not os.path.exists(wait)  # reading never asks
        with _engine(ctx).begin() as conn:
            conn.execute(text("UPDATE records SET updated_at = updated_at"))
        assert os.path.exists(wait)
        assert ctx.index_svc._repo.quiet_for() < 5
    assert not os.path.exists(db + "-indexing")
    assert not os.path.exists(wait)


def test_a_build_gives_way_to_a_save_and_keeps_nothing(ctx, sample, monkeypatch):
    monkeypatch.setattr(index_gate, "CHECK_EVERY", 1)
    repo = ctx.index_svc._repo
    db = _db(ctx)
    with repo.upkeep():
        # A save arriving while the build runs (its mark is newer than the
        # build's start): SQLite interrupts the build and rolls it back.
        later = time.time() + 60
        open(db + "-indexing.wait", "a").close()
        os.utime(db + "-indexing.wait", (later, later))
        with pytest.raises(IndexBuildYielded):
            repo.create(sample)
        assert sample.name not in repo.existing()
        # The session is fine afterwards, and the save goes in at once.
        ctx.record_svc.add("study", "sample", {"depth": 1.5}, with_labels=False)
        ctx.commit()

        os.unlink(db + "-indexing.wait")
        repo.create(sample)  # nobody asked: built
    assert sample.name in repo.existing()


class _Repo:
    """A repository whose first build gives way once, and that has been quiet
    only after a few looks."""

    def __init__(self, quiet: list[float]) -> None:
        self.quiet = quiet
        self.made: list[str] = []
        self.refreshed = 0
        self.gave_way = False

    def existing(self) -> set[str]:
        return set(self.made)

    def create(self, spec) -> None:
        if not self.gave_way:
            self.gave_way = True
            raise IndexBuildYielded()
        self.made.append(spec.name)

    def drop(self, name: str) -> None:
        self.made.remove(name)

    def refresh_statistics(self, reason: str) -> None:
        self.refreshed += 1

    def upkeep(self):
        from contextlib import nullcontext

        return nullcontext()

    def quiet_for(self) -> float:
        return self.quiet.pop(0) if self.quiet else float("inf")


def test_reconcile_waits_for_quiet_and_starts_again_after_giving_way(
    ctx, sample, monkeypatch
):
    monkeypatch.setattr(index_service, "QUIET_SECONDS", 0.05)
    monkeypatch.setattr(index_service.time, "sleep", lambda s: None)
    ctx.index_svc.set_indexed("sample", "depth", True)
    ctx.index_svc.set_indexed("sample", "code", True)
    repo = _Repo(quiet=[0.0, 0.01])  # saving at first, then quiet
    monkeypatch.setattr(ctx.index_svc, "_repo", repo)

    seen: list[IndexProgress] = []
    result = ctx.index_svc.reconcile(progress=seen.append)
    assert len(result.created) == 2
    assert result.yielded == 1 and not result.stopped
    assert repo.refreshed == 1
    assert seen[0].waiting and seen[0].total == 2 and seen[0].schema_label
    building = [p for p in seen if not p.waiting]
    assert [p.done for p in building] == [0, 0, 1, 2]  # 0 twice: it gave way once
    assert building[-1].field_label == ""  # the end


def test_reconcile_stops_while_waiting_when_told(ctx, sample, monkeypatch):
    monkeypatch.setattr(index_service.time, "sleep", lambda s: None)
    ctx.index_svc.set_indexed("sample", "depth", True)
    monkeypatch.setattr(ctx.index_svc, "_repo", _Repo(quiet=[0.0] * 100))
    result = ctx.index_svc.reconcile(should_stop=lambda: True)
    assert result.stopped and not result.created


def test_one_process_at_a_time_keeps_the_indexes(ctx, sample):
    ctx.index_svc.set_indexed("sample", "depth", True)
    with jobs.pid_lock(ctx.config.civex_dir / jobs.LOCK):  # another process
        assert jobs.upkeep_running(ctx)
        assert jobs.run_upkeep(ctx) is None
        assert jobs.queue_upkeep(ctx) == jobs.QUEUED_ELSEWHERE
    result = jobs.run_upkeep(ctx)
    assert result is not None and result.created == [sample.name]
    assert jobs.queue_upkeep(ctx) == jobs.IN_STEP


def test_the_cli_starts_a_process_of_its_own(ctx, sample, background_upkeep):
    ctx.index_svc.set_indexed("sample", "depth", True)
    assert jobs.queue_upkeep(ctx) == jobs.QUEUED_STARTED
    assert background_upkeep == [ctx.config.project_root]
