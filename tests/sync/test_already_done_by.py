"""A device's deletes that the authority found already made by someone else are
shown as that person's, not as the device's own synced change: the history keeps
what the authority says happened, and undoing the device's change never brings
back what the other person deleted."""

from __future__ import annotations

import uuid

from civex.testing.peers import build_study, connect, device

from .test_delete_race_helpers import live_ids

TOTAL, ELSEWHERE = 20, 8


def _setup(project):
    hub = project("hub")
    jamie, desk = device(project, hub, "jamie"), device(project, hub, "desk")
    jamie.audit_svc._actor = "jamie"
    desk.audit_svc._actor = "desk"
    first = build_study(jamie)
    ids = [first.id] + [
        jamie.record_svc.add("study", "encounter", {"site": f"s{i}", "depth": 1.0}).id
        for i in range(TOTAL - 1)
    ]
    jamie.commit()
    connect(jamie)
    jamie.sync_svc.sync()
    connect(desk)
    desk.sync_svc.sync()
    # jamie deletes some and syncs; the desktop, not having seen that, deletes all
    jamie.record_svc.delete_many([str(i) for i in ids[:ELSEWHERE]], force=True)
    jamie.commit()
    jamie.sync_svc.sync()
    desk.record_svc.delete_many([str(i) for i in ids], force=True)
    desk.commit()
    return hub, jamie, desk, ids


def _desk_batch(desk):
    events, _ = desk.history_svc.events()
    own = [
        e for e in events if e.batch and e.batch.kind == "delete" and e.actor == "desk"
    ]
    assert len(own) == 1
    return own[0]


def test_the_device_shows_what_was_already_deleted_as_the_others(project):
    hub, jamie, desk, ids = _setup(project)
    desk.sync_svc.sync()
    desk.sync_svc.sync()  # a further sync changes nothing
    event = _desk_batch(desk)
    assert event.count == TOTAL - ELSEWHERE
    assert event.already_done == {
        "count": ELSEWHERE,
        "by": ["jamie"],
        "own": 0,
        "own_devices": [],
    }
    assert [(p["action"], p["count"]) for p in event.parts] == [
        ("delete", TOTAL - ELSEWHERE)
    ]
    # the other's own deletes are listed once, as theirs
    events, _ = desk.history_svc.events()
    theirs = [
        e for e in events if e.actor == "jamie" and e.batch and e.batch.kind == "delete"
    ]
    assert sum(e.count for e in theirs) == ELSEWHERE
    assert desk.sync_repo.count_pending() == 0


def test_the_authoritys_own_history_reads_the_same(project):
    hub, jamie, desk, ids = _setup(project)
    desk.sync_svc.sync()
    events, _ = hub.history_svc.events()
    mine = [e for e in events if e.batch and e.actor == "desk"]
    assert len(mine) == 1
    assert mine[0].count == TOTAL - ELSEWHERE
    assert mine[0].already_done["count"] == ELSEWHERE
    assert mine[0].already_done["by"] == ["jamie"]


def test_the_authority_names_what_it_found_already_done(project):
    hub, jamie, desk, ids = _setup(project)
    desk.sync_svc.sync()
    ops = [hub.sync_repo.get_op(i) for i in _own_entry_ids(desk)]
    assert sum(1 for o in ops if o and o.already_done) == ELSEWHERE
    # a resend gets the same answer
    again = [hub.sync_repo.get_op(i) for i in _own_entry_ids(desk)]
    assert [o.already_done for o in again] == [o.already_done for o in ops]


def _own_entry_ids(ctx):
    from sqlalchemy import select

    from civex.db.models import AuditLog

    return list(
        ctx._session.scalars(
            select(AuditLog.id).where(
                AuditLog.action == "delete", AuditLog.actor == "desk"
            )
        )
    )


def test_undoing_the_devices_delete_leaves_what_the_other_deleted(project):
    hub, jamie, desk, ids = _setup(project)
    desk.sync_svc.sync()
    batch = _desk_batch(desk).batch.id
    done = desk.history_svc.revert_batch(batch, dry_run=False)
    desk.commit()
    assert done.applied == TOTAL - ELSEWHERE
    assert live_ids(desk) == set(ids[ELSEWHERE:])
    desk.sync_svc.sync()
    jamie.sync_svc.sync()
    assert live_ids(hub) == set(ids[ELSEWHERE:])
    assert live_ids(jamie) == set(ids[ELSEWHERE:])


def _three(project, extra=()):
    hub = project("hub")
    names = ["jamie", "alice", "desk", *extra]
    ctxs = {n: device(project, hub, n) for n in names}
    for n, c in ctxs.items():
        c.audit_svc._actor = n
    record = build_study(ctxs["jamie"])
    connect(ctxs["jamie"])
    ctxs["jamie"].sync_svc.sync()
    for n in names[1:]:
        connect(ctxs[n])
        ctxs[n].sync_svc.sync()
    return hub, ctxs, record


def _do(ctx, fn):
    fn()
    ctx.commit()
    ctx.sync_svc.sync()


def _desk_events(desk):
    events, _ = desk.history_svc.events()
    return [
        e
        for e in events
        if e.actor == "desk"
        and e.device != "laptop"
        and e.entry
        and e.entry.action == "delete"
    ]


def test_a_delete_that_conflicted_is_not_called_already_done(project):
    hub, c, record = _three(project)
    rid = str(record.id)
    _do(c["jamie"], lambda: c["jamie"].record_svc.delete(rid, force=True))
    _do(c["jamie"], lambda: c["jamie"].record_svc.restore(rid))
    c["alice"].sync_svc.sync()
    _do(
        c["alice"],
        lambda: c["alice"].record_svc.update(rid, {"site": "edited"}),
    )
    c["desk"].record_svc.delete(rid, force=True)  # has not seen any of it
    c["desk"].commit()
    c["desk"].sync_svc.sync()
    assert all(e.already_done is None for e in _desk_events(c["desk"]))
    assert not any(
        hub.sync_repo.get_op(i).already_done for i in _own_entry_ids(c["desk"])
    )


def test_it_names_the_latest_delete_since_the_last_restore(project):
    hub, c, record = _three(project, extra=("bob",))
    rid = str(record.id)
    _do(c["jamie"], lambda: c["jamie"].record_svc.delete(rid, force=True))
    c["alice"].sync_svc.sync()
    _do(c["alice"], lambda: c["alice"].record_svc.restore(rid))
    c["bob"].sync_svc.sync()
    _do(c["bob"], lambda: c["bob"].record_svc.delete(rid, force=True))
    c["desk"].record_svc.delete(rid, force=True)  # not seen the others
    c["desk"].commit()
    c["desk"].sync_svc.sync()
    [event] = _desk_events(c["desk"])
    assert event.already_done["by"] == ["bob"]
    assert event.already_done["count"] == 1  # a single change stays one entry
    assert event.count == 1


def test_the_same_person_on_another_device_is_said_so(project):
    hub, c, record = _three(project, extra=("laptop",))
    c["laptop"].audit_svc._actor = "desk"
    rid = str(record.id)
    _do(c["laptop"], lambda: c["laptop"].record_svc.delete(rid, force=True))
    c["desk"].record_svc.delete(rid, force=True)
    c["desk"].commit()
    c["desk"].sync_svc.sync()
    [event] = _desk_events(c["desk"])
    assert event.already_done == {
        "count": 1,
        "by": [],
        "own": 1,
        "own_devices": ["laptop"],
    }


def test_an_answer_without_the_field_is_not_taken_as_already_done(project):
    from civex.domain.sync import OpResult

    answer = {"op_id": str(uuid.uuid4()), "status": "applied", "hub_seq": 5}
    assert OpResult.from_dict(answer).already_done is False
    assert "already_done" not in OpResult.from_dict(answer).to_dict()


def test_an_actions_entries_are_never_called_already_done(project):
    from .test_bulk_changes import Flow
    from .test_bulk_push import send

    hub = project("hub")
    f = Flow(project)
    enc = f.make("mine", "encounter", {"site": "a"})
    kid = f.make("mine", "recording", {"label": "x", "must": "m"}, str(enc))
    send(hub, f.structure + f.take())
    gone = f.deleted([enc, kid])
    assert len({e.op for e in gone}) == 1 and gone[0].op  # one action
    send(hub, gone)
    ops = [hub.sync_repo.get_op(e.id) for e in gone]
    assert len(ops) == 2 and not any(o.already_done for o in ops)


import pytest  # noqa: E402


@pytest.mark.parametrize("seed", [6, 18])
def test_the_seeds_that_flagged_an_actions_entries_converge(project, seed):
    """Flagging a delete that found the record deleted by its own action's
    cascade made a device end with a live record (seeds 6 and 18)."""
    from civex.testing.invariants import scenario

    assert scenario(project, project("authority"), seed) == []
