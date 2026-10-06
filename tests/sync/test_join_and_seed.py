"""Joining and seeding while the projects are in use: what changes on either side
while the copy is being made must not be lost, and nothing the copy needs first
may arrive second."""

from __future__ import annotations

from datetime import timedelta

import civex.services.sync_service as sync_service
from civex.db.models import Record, Schema

from .peers import build_study, connect, device, push, snapshots


def _record_ids(ctx) -> set[str]:
    return {s["id"] for s in snapshots(ctx)["record"]}


def test_a_join_misses_nothing_when_the_authority_removes_something_meanwhile(
    project, authority, monkeypatch
):
    """Pages are read one request at a time. Something removed for good between
    two of them must not shift the next page past a record that never changed
    (nothing in the feed would bring it back)."""
    monkeypatch.setattr(sync_service, "SNAPSHOT_PAGE", 2)
    build_study(authority)
    made = [
        authority.record_svc.add("study", "encounter", {"site": f"s{i}"})
        for i in range(5)
    ]
    authority.commit()
    phone = device(project, authority, "phone")

    original = sync_service.SyncService._join

    def join_and_purge_after_first_page(self, transport):
        real = transport.snapshot

        def snapshot(kind, after, limit):
            page = real(kind, after, limit)
            if kind == "record" and not after:
                # the first page is read; the oldest record goes for good
                authority.record_svc.delete(str(made[0].id))
                authority.record_svc.purge(str(made[0].id))
                authority.commit()
            return page

        transport.snapshot = snapshot
        try:
            return original(self, transport)
        finally:
            del transport.snapshot

    monkeypatch.setattr(
        sync_service.SyncService, "_join", join_and_purge_after_first_page
    )
    assert connect(phone) == "joined"

    assert _record_ids(phone) == _record_ids(authority)


def test_a_join_applies_a_record_after_the_one_it_sits_under(project, authority):
    """Records arrive oldest first, but a child can be older than its parent (it
    was made on a device whose clock was behind). The parent must still be
    written first: the database refuses a child without one."""
    build_study(authority)
    authority.schema_svc.create("sample", parent="encounter")
    authority.schema_svc.add_field("sample", "label", "string")
    authority.dataset_svc.update("study", schemas=["encounter", "sample"])
    parent = authority.record_svc.add("study", "encounter", {"site": "late"})
    child = authority.record_svc.add(
        "study", "sample", {"label": "early"}, parent_record_id=str(parent.id)
    )
    authority.commit()
    s = authority._session
    row = s.get(Record, child.id)
    row.created_at = s.get(Record, parent.id).created_at - timedelta(days=1)
    authority.commit()

    phone = device(project, authority, "phone")
    assert connect(phone) == "joined"

    assert _record_ids(phone) == _record_ids(authority)


def test_a_join_applies_a_schema_after_the_one_it_extends(project, authority):
    authority.schema_svc.create("base")
    authority.schema_svc.create("derived")
    authority.commit()
    s = authority._session
    derived = s.query(Schema).filter_by(name="derived").one()
    base = s.query(Schema).filter_by(name="base").one()
    derived.parent_id = base.id
    derived.created_at = base.created_at - timedelta(days=1)
    authority.commit()

    phone = device(project, authority, "phone")
    assert connect(phone) == "joined"

    names = {s["name"] for s in snapshots(phone)["schema"]}
    assert {"base", "derived"} <= names


def test_an_edit_made_while_seeding_is_still_sent(project, authority, monkeypatch):
    """Seeding sends things as they are when each page is read. An edit made
    after its page went (the web UI stays usable) has to follow as an ordinary
    change, not be marked as sent along with everything else."""
    monkeypatch.setattr(sync_service, "PUSH_BATCH", 1)
    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    edited = False

    original = sync_service.SyncService._seed

    def seed_and_edit_after_the_record_went(self, transport):
        real = transport.push

        def push(entries):
            nonlocal edited
            result = real(entries)
            if not edited and any(e.entity_id == record.id for e in entries):
                edited = True
                laptop.record_svc.update(
                    str(record.id), {"site": "after", "depth": 1.0}
                )
                laptop.commit()
            return result

        transport.push = push
        try:
            return original(self, transport)
        finally:
            del transport.push

    monkeypatch.setattr(
        sync_service.SyncService, "_seed", seed_and_edit_after_the_record_went
    )
    assert connect(laptop) == "seeded"
    assert edited
    assert laptop.sync_repo.count_pending() == 1

    laptop.sync_svc.sync()

    held = authority.sync_repo.snapshot("record", record.id)
    assert held is not None
    site = next(
        f for f in authority.schema_svc.get("encounter").fields if f.name == "site"
    )
    assert held["data"][str(site.id)] == "after"


def test_an_edit_on_the_authority_saved_during_a_push_is_numbered_before_it(
    pair, authority, monkeypatch
):
    """A change made on the authority itself is numbered when someone next asks.
    If it was saved after a push began but before the push merged with it, the
    push's result already includes it; numbered after the push, it would carry
    the state from before the push, and every device would apply that last."""
    laptop, phone, record = pair
    authority.record_svc.update(str(record.id), {"site": "server", "depth": 1.0})
    authority.commit()
    laptop.record_svc.update(str(record.id), {"site": "x", "depth": 2.0})
    laptop.commit()

    real_sequence = authority.sync_repo.sequence_local_entries
    real_push = authority.authority_svc.push
    skip = False

    def sequence():
        # The push's first look happens before the edit was saved.
        nonlocal skip
        if skip:
            skip = False
            return 0
        return real_sequence()

    def pushing(*args, **kwargs):
        nonlocal skip
        skip = True
        return real_push(*args, **kwargs)

    monkeypatch.setattr(authority.sync_repo, "sequence_local_entries", sequence)
    monkeypatch.setattr(authority.authority_svc, "push", pushing)
    push(authority, laptop)  # straight to the push: nothing numbered it first
    monkeypatch.undo()
    phone.sync_svc.sync()

    assert snapshots(phone)["record"] == snapshots(authority)["record"]
