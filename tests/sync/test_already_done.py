"""A pushed delete of a record already deleted on the authority (or a restore of
one already live) is already done: answered as taken, written no more (no
second history entry, no settling "sync" entry), and the rest of the push stays
on the bulk path."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timedelta

import pytest

from civex.domain.sync import SyncEntry

from .test_bulk_changes import Flow
from .test_bulk_push import send


def again(entries: list[SyncEntry]) -> list[SyncEntry]:
    """The same changes made by another device a moment later."""
    out = []
    for e in entries:
        at = (datetime.fromisoformat(e.timestamp) + timedelta(seconds=2)).isoformat()
        out.append(
            dataclasses.replace(e, id=uuid.uuid4(), timestamp=at, hlc=None, actor="b")
        )
    return out


def history(ctx, rid, action):
    return [
        e
        for e in ctx.sync_repo.numbered_entries("record", rid, 0)
        if e.action == action
    ]


@pytest.fixture()
def spy(project):
    ctx = project("authority")
    calls = {"delete": [], "restore": [], "settled": 0}
    repo, svc = ctx.sync_repo, ctx.authority_svc
    real_d, real_r, real_s = repo.soft_delete_records, repo.restore_records, svc._settle

    def d(items):
        calls["delete"].append(len(items))
        return real_d(items)

    def r(ids):
        calls["restore"].append(len(ids))
        return real_r(ids)

    def s(who, entry):
        calls["settled"] += 1
        return real_s(who, entry)

    repo.soft_delete_records, repo.restore_records, svc._settle = d, r, s
    return ctx, calls


def test_a_delete_already_made_is_acknowledged_and_written_once(project, spy):
    ctx, calls = spy
    f = Flow(project)
    ids = f.many(5)
    send(ctx, f.structure + f.take())
    gone = f.deleted(ids)
    send(ctx, gone)
    head = ctx.sync_repo.head_seq()
    dup = again(gone)
    calls["delete"].clear()
    calls["settled"] = 0
    answers, new_head = send(ctx, dup)
    assert [a[1] for a in answers] == ["applied"] * 5
    assert new_head == head  # nothing numbered
    for rid in ids:
        assert len(history(ctx, rid, "delete")) == 1
        assert not [
            e
            for e in ctx.sync_repo.numbered_entries("record", rid, 0)
            if e.actor == "sync"
        ]
    assert calls["delete"] == [] and calls["settled"] == 0  # bulk path, no writes
    # Sent again, the same answers, none of it done again.
    again_answers, _ = send(ctx, dup)
    assert [a[:2] for a in again_answers] == [a[:2] for a in answers]
    assert all(a[5] for a in again_answers)


def test_a_push_of_100_deletes_half_done_writes_the_other_half_in_one_action(
    project, spy
):
    ctx, calls = spy
    f = Flow(project)
    ids = f.many(100)
    send(ctx, f.structure + f.take())
    gone = f.deleted(ids)
    send(ctx, again(gone[:50]))  # another device deleted the first 50
    calls["delete"].clear()
    calls["settled"] = 0
    both = gone  # this device's delete of all 100
    answers, _ = send(ctx, both)
    assert [a[1] for a in answers] == ["applied"] * len(both)
    # The 50 not yet deleted went in as one bulk write, the rest were skipped.
    assert calls["delete"] == [50] and calls["settled"] == 0
    for rid in ids[50:]:
        assert len(history(ctx, rid, "delete")) == 1
    assert (
        len({str(e.batch) for rid in ids[50:] for e in history(ctx, rid, "delete")})
        == 1
    )


def test_a_restore_of_a_record_already_live_is_acknowledged_and_not_written(
    project, spy
):
    ctx, calls = spy
    f = Flow(project)
    ids = f.many(6)
    send(ctx, f.structure + f.take())
    send(ctx, f.deleted(ids))
    back = f.restored(ids)
    send(ctx, back[:3])
    calls["restore"].clear()
    calls["settled"] = 0
    answers, _ = send(ctx, again(back[:3]) + back[3:])
    assert [a[1] for a in answers] == ["applied"] * 6
    assert calls["restore"] == [3] and calls["settled"] == 0
    for rid in ids:
        assert len(history(ctx, rid, "restore")) == 1


def test_a_delete_made_on_two_devices_is_settled_once_and_both_end_synced(project):
    from civex.testing.peers import build_study, connect, device

    hub = project("hub")
    a, b = device(project, hub, "a"), device(project, hub, "b")
    record = build_study(a)
    connect(a)
    a.sync_svc.sync()
    connect(b)
    b.sync_svc.sync()
    a.record_svc.delete(str(record.id), force=True)
    a.commit()
    a.sync_svc.sync()
    b.record_svc.delete(str(record.id), force=True)  # not yet seen the other's
    b.commit()
    b.sync_svc.sync()
    assert len(history(hub, record.id, "delete")) == 1
    assert not [
        e
        for e in hub.sync_repo.numbered_entries("record", record.id, 0)
        if e.actor == "sync"
    ]
    assert b.sync_repo.count_pending() == 0
