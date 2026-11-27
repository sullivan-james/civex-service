"""Copying a project, either way, says how far it has got; the history from before
joining is not downloaded but read from the server when looked at; and a copy that stops part way
is finished by connecting again, never synced from half a copy."""

from __future__ import annotations

import pytest

import civex.services.sync_service as sync_service
from civex.domain.sync import COPYING, FILLING, SyncError
from civex.services.sync_worker import SyncWorker

from civex.testing.peers import build_study, connect, device, flaky, snapshots


@pytest.fixture()
def study(project, authority, monkeypatch):
    """An authority holding a study of 30 records, filled by a laptop."""
    monkeypatch.setattr(sync_service, "SNAPSHOT_PAGE", 7)
    monkeypatch.setattr(sync_service, "SNAPSHOT_PAGE_BIG", 7)
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


def test_a_copy_downloads_no_history_and_the_worker_never_fetches_it(
    project, authority, study
):
    phone = device(project, authority, "phone")
    assert connect(phone) == "joined"
    head = authority.sync_repo.head_seq()
    assert phone.sync_repo.meta().history_from == head  # where its history starts
    assert not hasattr(phone.sync_svc, "fetch_history")

    worker = SyncWorker(lambda: phone.sync_svc._config, lambda config: phone)
    worker._open = lambda config: _Unclosed(phone)  # the test's context stays open
    for _ in range(5):
        worker.tick()
    assert phone.history_svc.page(limit=1000) == []  # nothing stored
    assert phone.sync_repo.meta().history_from == head


def test_earlier_history_is_read_from_the_server_and_not_stored(
    project, authority, study
):
    phone = device(project, authority, "phone")
    connect(phone)
    theirs = {e.id for e in authority.history_svc.page(limit=1000)}
    seen: list = []
    before = None
    pages = 0
    while True:
        page = phone.sync_svc.earlier(before, limit=7)
        assert len(page.entries) <= 7
        seen += [e.id for e in page.entries]
        pages += 1
        before = page.next_before
        if before is None:
            break
    assert pages > 1
    assert set(seen) == theirs and len(seen) == len(theirs)
    stamps = [e.hub_seq for e in phone.sync_svc.earlier(None, 7).entries]
    assert stamps == sorted(stamps, reverse=True)  # newest first
    assert phone.history_svc.page(limit=1000) == []  # none of it was kept
    assert phone.sync_repo.meta().history_from == authority.sync_repo.head_seq()


def test_earlier_events_carry_changes_and_group_a_batch(project, authority, study):
    phone = device(project, authority, "phone")
    connect(phone)
    page = phone.sync_svc.earlier(None, 200)
    events = phone.history_svc.events_of_entries(page.entries)
    assert events and sum(e.count for e in events) == len(page.entries)
    assert [e.timestamp for e in events] == sorted(
        (e.timestamp for e in events), reverse=True
    )
    single = next(e for e in events if e.entry and e.entry.entity_type == "record")
    assert single.entry.changes  # worked out like local history
    only = phone.history_svc.events_of_entries(
        page.entries, under=str(single.entry.entity_id)
    )
    assert only and all(e.entry.entity_id == single.entry.entity_id for e in only)
    assert phone.history_svc.page(limit=1000) == []


def test_earlier_history_is_empty_without_a_copy_point(project, authority, study):
    assert authority.sync_svc.earlier(None, 10).entries == []


def test_earlier_history_offline_says_so_over_the_api(project, authority, study):
    from civex.server.routers.audit import earlier_audit

    phone = device(project, authority, "phone", flaky=True)
    connect(phone)
    flaky(phone).fail("feed", times=5)
    assert phone.sync_svc.status().earlier_history is True
    r = earlier_audit(None, 25, None, phone)
    assert (r.items, r.next_before, r.offline) == ([], None, True)


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
