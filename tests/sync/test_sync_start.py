"""What a sync does before its first push stays cheap however many changes are
unsent (the records above them are found by id, nothing is loaded or named),
and a long wait says what it is waiting on."""

from __future__ import annotations


import pytest
from sqlalchemy import update

import civex.services.sync_service as sync_service
from civex.db.models import Record
from civex.domain.sync import PREPARING, PULLING, PUSHING
from civex.testing.peers import connect, device


def tree(project, authority):
    """site > visit > sample, and a second site, synced to a second device."""
    a = device(project, authority, "a")
    a.schema_svc.create("site")
    a.schema_svc.add_field("site", "name", "string")
    a.schema_svc.create("visit", parent="site")
    a.schema_svc.add_field("visit", "when", "string")
    a.schema_svc.create("sample", parent="visit")
    a.schema_svc.add_field("sample", "tag", "string")
    a.dataset_svc.create("survey")
    site = a.record_svc.add("survey", "site", {"name": "x"})
    other = a.record_svc.add("survey", "site", {"name": "y"})
    visit = a.record_svc.add(
        "survey", "visit", {"when": "may"}, parent_record_id=str(site.id)
    )
    sample = a.record_svc.add(
        "survey", "sample", {"tag": "t"}, parent_record_id=str(visit.id)
    )
    a.commit()
    connect(a)
    return a, site, other, visit, sample


def old_above(ctx, dirty):
    """What `_above_dirty` used to work out, by loading and naming."""
    ids = [eid for kind, eid in dirty if kind == "record"]
    if not ids:
        return set(ids)
    labelled = ctx.record_svc.labels([str(i) for i in ids])
    trails = ctx.record_svc.ancestor_trails(labelled)
    return set(ids) | {a.id for t in trails.values() for a in t}


def above(ctx):
    dirty = ctx.sync_repo.dirty_entities()
    return ctx.sync_svc._above_dirty(dirty), old_above(ctx, dirty)


def test_the_records_above_an_unsent_change_are_the_same_as_before(project, authority):
    a, site, other, visit, sample = tree(project, authority)
    a.record_svc.update(str(sample.id), {"tag": "u"})
    a.commit()
    new, old = above(a)
    assert new == old == {sample.id, visit.id, site.id}
    assert other.id not in new

    # A change to a deleted parent's child, and to a top record, still agree.
    a.record_svc.update(str(other.id), {"name": "z"})
    a.commit()
    a.sync_svc.sync()
    a.record_svc.update(str(visit.id), {"when": "june"})
    a.commit()
    new, old = above(a)
    assert new == old == {visit.id, site.id}


def test_nothing_unsent_means_nothing_above(project, authority):
    a, *_ = tree(project, authority)
    a.sync_svc.sync()
    assert a.sync_svc._above_dirty(a.sync_repo.dirty_entities()) == set()


def test_the_records_above_follow_a_move_between_calls(project, authority):
    a, site, other, visit, sample = tree(project, authority)
    a.record_svc.update(str(sample.id), {"tag": "u"})
    a.commit()
    first, _ = above(a)
    assert site.id in first and other.id not in first
    # The visit is put under the other site (as a pull would do).
    a._session.execute(
        update(Record).where(Record.id == visit.id).values(parent_record_id=other.id)
    )
    a.commit()
    second, old = above(a)
    assert second == old == {sample.id, visit.id, other.id}


def test_a_replay_with_nothing_held_looks_at_nothing(project, authority, monkeypatch):
    a, site, other, visit, sample = tree(project, authority)
    a.record_svc.update(str(sample.id), {"tag": "u"})
    a.commit()

    def boom(self, dirty):
        raise AssertionError("worked out what is above with nothing held")

    monkeypatch.setattr(sync_service.SyncService, "_above_dirty", boom)
    assert a.sync_svc._replay_held(a.sync_repo.dirty_entities()) is False


def test_a_held_move_is_still_replayed(project, authority):
    """A move held for an unsent edit to a child goes in once that is sent."""
    a, site, other, visit, sample = tree(project, authority)
    b = device(project, authority, "b")
    connect(b)
    a.dataset_svc.create("archive")
    a.commit()
    a.sync_svc.sync()
    b.sync_svc.sync()
    b.record_svc.update(str(sample.id), {"tag": "mine"})
    b.commit()
    a.record_svc.move("archive", ids=[str(site.id)])
    a.commit()
    a.sync_svc.sync()
    b.sync_svc.sync()  # pulls the move while holding an unsent child edit
    b.sync_svc.sync()
    a.sync_svc.sync()
    archive = str(a.dataset_svc.get("archive").id)
    for ctx in (authority, a, b):
        for rid in (site.id, visit.id, sample.id):
            assert ctx.sync_repo.snapshot("record", rid)["dataset_id"] == archive
    assert b.sync_svc.conflicts() == []


@pytest.fixture()
def small_pages(monkeypatch):
    monkeypatch.setattr(sync_service, "FEED_PAGE", 5)
    monkeypatch.setattr(sync_service, "PUSH_BATCH", 5)


def test_a_long_start_says_what_it_is_on(project, authority, small_pages):
    a, site, other, visit, sample = tree(project, authority)
    b = device(project, authority, "b")
    connect(b)
    b.sync_svc.sync()
    for i in range(14):
        authority.record_svc.add(
            "survey", "site", {"name": f"in{i}"}, with_labels=False
        )
    authority.commit()
    for i in range(12):
        b.record_svc.add("survey", "site", {"name": f"out{i}"}, with_labels=False)
    b.commit()
    pending = b.sync_repo.count_pending()
    assert pending > 5

    seen = []
    b.sync_svc.sync(seen.append)

    pulled = [p for p in seen if p.phase == PULLING]
    assert pulled and all(p.total for p in pulled)
    first = [
        p.done
        for p in pulled[: pulled.index(next(p for p in pulled[1:] if p.done == 0))]
    ]
    assert (
        first == sorted(first) and len(first) > 1
    )  # (the pull after the push starts again)
    assert all(p.done <= p.total for p in pulled)
    phases = [p.phase for p in seen]
    assert phases.index(PULLING) < phases.index(PREPARING) < phases.index(PUSHING)
    prepared = next(p for p in seen if p.phase == PREPARING)
    assert prepared.total == pending
    pushed = [p for p in seen if p.phase == PUSHING]
    assert pushed[-1].done == pushed[-1].total == pending


def test_a_short_sync_says_nothing(project, authority):
    a, site, *_ = tree(project, authority)
    b = device(project, authority, "b")
    connect(b)
    a.record_svc.update(str(site.id), {"name": "q"})
    a.commit()
    seen = []
    a.sync_svc.sync(seen.append)
    b.sync_svc.sync(seen.append)
    assert seen == []
