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
    assert event.already_done == {"count": ELSEWHERE, "by": ["jamie"]}
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
