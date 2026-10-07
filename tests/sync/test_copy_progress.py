"""Copying a project, either way, says how far it has got; the history from before
joining arrives after the copy, a piece at a time; and a copy that stops part way
is finished by connecting again, never synced from half a copy."""

from __future__ import annotations

import pytest

import civex.services.sync_service as sync_service
from civex.domain.sync import COPYING, FILLING, HISTORY, SyncError
from civex.services.sync_worker import SyncWorker

from .peers import build_study, connect, device, flaky, snapshots


@pytest.fixture()
def study(project, authority, monkeypatch):
    """An authority holding a study of 30 records, filled by a laptop."""
    monkeypatch.setattr(sync_service, "SNAPSHOT_PAGE", 7)
    monkeypatch.setattr(sync_service, "FEED_PAGE", 5)
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    for i in range(29):
        laptop.record_svc.add("study", "encounter", {"site": f"s{i}", "depth": 1.0})
    laptop.commit()
    connect(laptop)
    return laptop


def test_a_join_says_how_far_it_has_got(project, authority, study):
    phone = device(project, authority, "phone")
    seen = []
    phone.sync_svc.connect(
        "https://authority.test", phone._invite, progress=seen.append
    )

    assert seen and all(p.phase == COPYING for p in seen)
    total = sum(authority.sync_repo.entity_counts().values())
    assert all(p.total == total for p in seen)
    assert [p.done for p in seen] == sorted(p.done for p in seen)
    assert seen[-1].done == total
    assert {p.kind for p in seen} >= {"schema", "record"}


def test_filling_an_empty_authority_says_how_far_it_has_got(project, authority):
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    seen = []
    laptop.sync_svc.connect(
        "https://authority.test", laptop._invite, progress=seen.append
    )
    assert seen and all(p.phase == FILLING for p in seen)
    assert seen[-1].done == seen[-1].total == laptop.sync_repo.entity_count()


def test_history_from_before_joining_arrives_a_piece_at_a_time(
    project, authority, study
):
    phone = device(project, authority, "phone")
    assert connect(phone) == "joined"
    head = authority.sync_repo.head_seq()
    assert phone.sync_repo.meta().history_from == head

    seen = []
    assert phone.sync_svc.fetch_history(seen.append, pages=1) is False
    assert phone.sync_repo.meta().history_from == head  # more to come
    while not phone.sync_svc.fetch_history(seen.append, pages=1):
        pass

    assert all(p.phase == HISTORY and p.total == head for p in seen)
    assert phone.sync_repo.meta().history_from is None
    mine = {e.id for e in phone.history_svc.page(limit=1000)}
    theirs = {e.id for e in authority.history_svc.page(limit=1000)}
    assert theirs <= mine
    assert phone.sync_svc.fetch_history() is True  # nothing left: says so at once


def test_the_background_worker_fetches_history_in_slices(project, authority, study):
    phone = device(project, authority, "phone")
    connect(phone)
    shown = []
    worker = SyncWorker(
        lambda: phone.sync_svc._config,
        lambda config: phone,
        on_progress=shown.append,
    )
    worker._open = lambda config: _Unclosed(phone)  # the test's context stays open
    for _ in range(50):
        worker.tick()
        if phone.sync_repo.meta().history_from is None:
            break
    assert phone.sync_repo.meta().history_from is None
    assert shown[-1] is None  # done: nothing left to show
    assert any(p is not None and p.phase == HISTORY for p in shown)


def test_a_copy_that_stopped_part_way_is_finished_by_connecting_again(
    project, authority, study
):
    # A phone whose copy is cut off after its first page of records.
    other = device(project, authority, "other", flaky=True)
    other.sync_svc.check_connect(
        "https://authority.test", other._invite
    )  # (the transport)
    calls = {"records": 0}
    real = flaky(other)._inner.snapshot

    def cut_off(kind, after, limit):
        if kind == "record":
            calls["records"] += 1
            if calls["records"] == 2:
                raise SyncError("The network is down")
        return real(kind, after, limit)

    flaky(other)._inner.snapshot = cut_off
    with pytest.raises(SyncError):
        connect(other)
    assert other.sync_repo.meta().cursor == sync_service.JOINING
    with pytest.raises(SyncError, match="did not finish"):
        other.sync_svc.sync()

    flaky(other)._inner.snapshot = real
    assert connect(other) == "joined"
    assert snapshots(other) == snapshots(authority)
    assert other.sync_repo.meta().cursor == authority.sync_repo.head_seq()


class _Unclosed:
    """A context whose close does nothing, so a test can keep using it."""

    def __init__(self, ctx) -> None:
        self._ctx = ctx

    def __getattr__(self, name):
        return getattr(self._ctx, name)

    def close(self) -> None:
        pass
