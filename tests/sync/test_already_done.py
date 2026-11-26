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


def test_a_delete_already_made_by_another_change_is_written_down_too(project, spy):
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
    # Another change's delete is history too: it is what lets an undo of one
    # leave what the other also deleted. The record itself does not change.
    for rid in ids:
        assert len(history(ctx, rid, "delete")) == 2
    after = ctx.sync_repo.head_seq()
    # Sent again (the same change), the same answers, none of it done again.
    again_answers, again_head = send(ctx, dup)
    assert [a[:2] for a in again_answers] == [a[:2] for a in answers]
    assert all(a[5] for a in again_answers)
    assert again_head == after
    for rid in ids:
        assert len(history(ctx, rid, "delete")) == 2


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
    # The 50 not yet deleted went in as one bulk write; the rest are written
    # down as a second delete without changing the records.
    assert calls["delete"] == [50]
    for rid in ids[50:]:
        assert len(history(ctx, rid, "delete")) == 1
    for rid in ids[:50]:
        assert len(history(ctx, rid, "delete")) == 2
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


def test_a_delete_made_on_two_devices_is_written_down_twice_and_both_end_synced(
    project,
):
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
    assert len(history(hub, record.id, "delete")) == 2
    assert b.sync_repo.count_pending() == 0


def test_an_edit_that_changes_nothing_is_acknowledged_and_not_written(project, spy):
    from .test_bulk_changes import edit_entry

    ctx, _ = spy
    f = Flow(project)
    ids = f.many(1)
    creates = f.take()
    send(ctx, f.structure + creates)
    edit = edit_entry(creates[0])
    send(ctx, [edit])
    head = ctx.sync_repo.head_seq()
    answers, new_head = send(ctx, [dataclasses.replace(edit, id=uuid.uuid4())])
    assert answers[0][1] == "applied" and new_head == head
    assert len(history(ctx, ids[0], "update")) == 1


# -- a device whose change was already true on the authority ------------------


def _pair(project, n, extra=()):
    """Devices a and b both holding n records, and the hub's pushes counted."""
    from civex.testing.peers import build_study, connect, device

    hub = project("hub")
    a, b = device(project, hub, "a"), device(project, hub, "b")
    first = build_study(a)
    for name in extra:
        a.dataset_svc.create(name)
    ids = [str(first.id)] + [
        str(a.record_svc.add("study", "encounter", {"site": f"s{i}", "depth": 1.0}).id)
        for i in range(n - 1)
    ]
    a.commit()
    connect(a)
    a.sync_svc.sync()
    connect(b)
    b.sync_svc.sync()
    pushes: list[int] = []
    real = hub.authority_svc.push

    hub._done = []  # answers of a change already so there
    hub._align = False  # make each edit carry the date the hub's record holds

    def counted(who, entries):
        pushes.append(len(entries))
        if hub._align:
            entries = [_dated_as_held(hub, e) for e in entries]
        out = real(who, entries)
        hub._done += [r for r in out.results if r.replayed and r.hub_seq is None]
        return out

    hub.authority_svc.push = counted
    return hub, a, b, ids, pushes


def _dated_as_held(hub, e):
    """An edit as another device would have made it at the very moment the hub's
    record was last changed: the same values and the same date."""
    held = hub.sync_repo.snapshot("record", e.entity_id)["updated_at"]
    new = {**e.new_data, "updated_at": held}
    delta = e.delta
    if delta and "updated_at" in delta:
        delta = {**delta, "updated_at": {**delta["updated_at"], "after": held}}
    return dataclasses.replace(e, new_data=new, delta=delta)


def _level(hub, b, ids, pushes):
    """b has nothing unsent, a further sync sends nothing, and b's records are
    as the hub's."""
    b.sync_svc.sync()
    assert b.sync_repo.count_pending() == 0
    assert not b.sync_repo.pending_entries(10_000)
    pushes.clear()
    b.sync_svc.sync()
    assert pushes == []
    for rid in ids:
        h = hub.sync_repo.snapshot("record", uuid.UUID(rid))
        d = b.sync_repo.snapshot("record", uuid.UUID(rid))
        assert h["deleted_at"] == d["deleted_at"]
        assert h["dataset_id"] == d["dataset_id"] and h["data"] == d["data"]


def test_a_device_whose_delete_was_already_done_ends_synced_and_sends_nothing(project):
    hub, a, b, ids, pushes = _pair(project, 3)
    a.record_svc.delete_many(ids, force=True)
    a.commit()
    a.sync_svc.sync()
    b.record_svc.delete_many(ids, force=True)
    b.commit()
    pushes.clear()
    b.sync_svc.sync()
    assert sum(pushes) == 3  # it was sent, and answered as done
    _level(hub, b, ids, pushes)


def test_a_device_whose_edit_was_already_made_ends_synced_and_sends_nothing(project):
    hub, a, b, ids, pushes = _pair(project, 2)
    for ctx in (a, b):
        ctx.record_svc.update(ids[0], {"site": "same"})
        ctx.commit()
        if ctx is a:
            a.sync_svc.sync()
    pushes.clear()
    hub._align = True
    b.sync_svc.sync()
    hub._align = False
    assert hub._done  # it was answered as already so, and written no more
    _level(hub, b, ids, pushes)


def test_a_device_whose_move_was_already_made_ends_synced_and_sends_nothing(project):
    hub, a, b, ids, pushes = _pair(project, 2, extra=("other",))
    for ctx in (a, b):
        ctx.record_svc.move("other", ids=[ids[0]])
        ctx.commit()
        if ctx is a:
            a.sync_svc.sync()
    pushes.clear()
    hub._align = True
    b.sync_svc.sync()
    hub._align = False
    assert hub._done
    _level(hub, b, ids, pushes)


def test_pending_deletes_over_two_push_pages_half_already_done(project):
    hub, a, b, ids, pushes = _pair(project, 300)
    a.record_svc.delete_many(ids[:150], force=True)
    a.commit()
    a.sync_svc.sync()
    b.record_svc.delete_many(ids, force=True)
    b.commit()
    pushes.clear()
    b.sync_svc.sync()
    assert sum(pushes) == 300 and len(pushes) >= 2
    _level(hub, b, ids, pushes)
