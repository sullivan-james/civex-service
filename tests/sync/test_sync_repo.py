"""Sync's storage: things go in and out by snapshot, with their own ids."""

from __future__ import annotations

import uuid

import pytest

from civex.repositories.local.sync_repo import LocalSyncRepository


def repo(ctx) -> LocalSyncRepository:
    return LocalSyncRepository(ctx._session)


@pytest.fixture()
def populated(project):
    """A project with every kind of thing in it, and a second, empty one."""
    a, b = project("a"), project("b")
    a.schema_svc.create("encounter")
    a.schema_svc.add_field("encounter", "site", "string")
    a.schema_svc.add_field("encounter", "depth", "float")
    a.schema_svc.create("recording", parent="encounter")
    a.schema_svc.add_field("recording", "rate", "integer")
    a.dataset_svc.create("study")
    a.dataset_svc.update("study", schemas=["encounter", "recording"])
    a.view_svc.create("encounter", "all", columns=["site"])
    parent = a.record_svc.add("study", "encounter", {"site": "x", "depth": 1.5})
    a.record_svc.add(
        "study", "recording", {"rate": 48}, parent_record_id=str(parent.id)
    )
    a.commit()
    return a, b


def copy_everything(source, target) -> None:
    from civex.domain.sync import ENTITY_ORDER

    src, dst = repo(source), repo(target)
    for kind in ENTITY_ORDER:
        for snap in src.snapshots_page(kind, 0, 1000):
            dst.apply_snapshot(kind, snap)
    target.commit()


def test_a_whole_project_copies_by_snapshot_and_reads_back_identically(populated):
    a, b = populated
    copy_everything(a, b)

    from civex.domain.sync import ENTITY_ORDER

    for kind in ENTITY_ORDER:
        assert repo(a).snapshots_page(kind, 0, 1000) == repo(b).snapshots_page(
            kind, 0, 1000
        ), kind
    # And the copy is a working project, not just rows.
    assert len(b.record_svc.find("study", "encounter")) == 1
    assert b.dataset_svc.get("study").schemas == ["encounter", "recording"]


def test_applying_a_snapshot_again_changes_nothing(populated):
    a, b = populated
    copy_everything(a, b)
    before = {k: repo(b).snapshots_page(k, 0, 100) for k in ("schema", "record")}
    copy_everything(a, b)
    assert {k: repo(b).snapshots_page(k, 0, 100) for k in before} == before


def test_a_later_snapshot_updates_the_thing_in_place(populated):
    a, b = populated
    copy_everything(a, b)
    record = a.record_svc.find("study", "encounter")[0]
    a.record_svc.update(str(record.id), {"site": "y", "depth": 2.0})
    a.commit()
    snap = repo(a).snapshot("record", record.id)
    repo(b).apply_snapshot("record", snap)
    b.commit()
    assert b.record_svc.get(str(record.id)).data["site"] == "y"


def test_a_delete_stamps_what_goes_with_it_and_a_restore_brings_back_only_that(
    populated,
):
    from datetime import datetime, timedelta, timezone

    a, b = populated
    copy_everything(a, b)
    rs = repo(b)
    schema = b.schema_svc.get("recording")
    rec = b.record_svc.find("study", "recording")[0]
    alone = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rs.soft_delete("record", rec.id, alone)  # deleted on its own earlier
    rs.restore("record", rec.id)
    rs.soft_delete("record", rec.id, alone)
    stamp = alone + timedelta(days=1)
    rs.soft_delete("schema", schema.id, stamp)
    b.commit()
    assert (
        b.schema_svc._repo.get_by_id(schema.id, include_deleted=True).deleted_at
        == stamp
    )
    # The record was already deleted, so the schema's delete didn't re-stamp it
    # and its restore leaves it deleted.
    rs.restore("schema", schema.id)
    b.commit()
    assert b.schema_svc.get("recording")
    assert b.record_svc.labels([str(rec.id)])[0].deleted_at is not None


def test_the_counter_hands_out_each_number_once(project):
    ctx = project("auth")
    r = repo(ctx)
    assert [r.next_hub_seq() for _ in range(3)] == [1, 2, 3]
    assert r.head_seq() == 3


def test_every_project_has_its_own_id_and_can_take_anothers(project):
    a, b = project("a"), project("b")
    assert repo(a).meta().project_id != repo(b).meta().project_id
    repo(b).set_project_id(repo(a).meta().project_id)
    b.commit()
    assert repo(b).meta().project_id == repo(a).meta().project_id


def test_pending_changes_are_the_ones_made_here_and_not_yet_sent(populated):
    a, _ = populated
    r = repo(a)
    pending = r.pending_entries(1000)
    assert pending and all(e.action in ("create", "update") for e in pending)
    assert {(e.entity_type) for e in pending} >= {
        "schema",
        "field",
        "dataset",
        "record",
    }
    assert r.count_pending() == len(pending)
    # Oldest first: a thing is created before it is used.
    stamps = [e.timestamp for e in pending]
    assert stamps == sorted(stamps)
    assert ("schema", pending[0].entity_id) in r.dirty_entities() or r.dirty_entities()

    r.mark_all_synced()
    a.commit()
    assert r.pending_entries(10) == [] and r.dirty_entities() == set()


def test_what_the_authority_numbers_comes_back_in_order_and_pages(project):
    ctx = project("auth")
    ctx.schema_svc.create("thing")
    ctx.schema_svc.add_field("thing", "a", "string")
    ctx.commit()
    r = repo(ctx)
    assert r.entries_after(0, 10) == ([], False)  # nothing numbered yet
    assert r.sequence_local_entries() == 3  # the schema, the field, and the template

    first, more = r.entries_after(0, 2)
    assert [e.hub_seq for e in first] == [1, 2] and more is True
    rest, more = r.entries_after(2, 2)
    assert [e.hub_seq for e in rest] == [3] and more is False
    assert r.sequence_local_entries() == 0  # already numbered


def test_an_entry_from_elsewhere_is_kept_as_it_was_with_its_batch(project):
    from civex.domain.sync import SyncBatchInfo, SyncEntry

    ctx = project("device")
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="delete",
        entity_type="record",
        entity_id=uuid.uuid4(),
        old_data={"x": 1},
        new_data=None,
        timestamp="2026-03-04T10:00:00+00:00",
        actor="alice",
        device_id=str(uuid.uuid4()),
        hlc="0000000000001.0000",
        batch=SyncBatchInfo(
            uuid.uuid4(), "delete", None, None, "2026-03-04T10:00:00+00:00"
        ),
    )
    r = repo(ctx)
    r.insert_entry(entry, hub_seq=7)
    ctx.commit()
    assert r.has_entry(entry.id)
    (back,), _ = r.entries_after(6, 5)
    assert back.id == entry.id and back.hub_seq == 7 and back.actor == "alice"
    assert back.batch is not None and back.batch.kind == "delete"
    assert r.pending_entries(10) == []  # it is not ours to send


def test_devices_are_found_by_the_hash_of_their_token_until_revoked(project):
    r = repo(project("auth"))
    r.add_device("lab-laptop", "h1")
    assert r.device_by_token_hash("h1").name == "lab-laptop"
    assert r.device_by_token_hash("nope") is None
    assert r.revoke_device("lab-laptop") is True
    assert r.device_by_token_hash("h1") is None
    assert r.revoke_device("lab-laptop") is False
    assert r.revoke_device("never-existed") is False


def test_conflicts_are_listed_until_resolved(project):
    r = repo(project("auth"))
    c = r.add_conflict(
        kind="conflict",
        entity_type="record",
        entity_id=uuid.uuid4(),
        field="data.x",
        yours=1,
        theirs=2,
        op_id=uuid.uuid4(),
        device_name="laptop",
        message=None,
    )
    assert [x.id for x in r.list_conflicts()] == [c.id]
    assert r.count_conflicts() == 1
    r.resolve_conflict(c.id, "theirs")
    assert r.list_conflicts() == [] and r.count_conflicts("resolved") == 1
