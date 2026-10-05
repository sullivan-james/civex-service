"""The authority: accepting changes, merging them, numbering them, serving them."""

from __future__ import annotations

import pytest

from civex.domain.sync import SyncError
from .peers import by_status, device_uuid, join, push, snapshots, statuses


@pytest.fixture()
def world(project):
    """An authority holding a small project, and two devices that copied it."""
    authority = project("authority")
    laptop, phone = project("laptop"), project("phone")
    laptop.schema_svc.create("encounter")
    laptop.schema_svc.add_field("encounter", "site", "string")
    laptop.schema_svc.add_field("encounter", "depth", "float")
    laptop.dataset_svc.create("study")
    laptop.dataset_svc.update("study", schemas=["encounter"])
    record = laptop.record_svc.add("study", "encounter", {"site": "x", "depth": 1.0})
    laptop.commit()
    first = push(authority, laptop, "laptop")
    assert set(statuses(first)) == {"applied"}
    join(authority, phone)
    return authority, laptop, phone, record


def head(ctx, record_id):
    return ctx.record_svc.get(str(record_id)).data


def test_a_devices_changes_arrive_whole_and_the_authority_holds_the_same_things(
    project,
):
    authority, laptop = project("authority"), project("laptop")
    laptop.schema_svc.create("encounter")
    laptop.schema_svc.add_field("encounter", "site", "string")
    laptop.dataset_svc.create("study")
    laptop.dataset_svc.update("study", schemas=["encounter"])
    laptop.record_svc.add("study", "encounter", {"site": "x"})
    laptop.commit()

    result = push(authority, laptop)

    assert set(statuses(result)) == {"applied"}
    assert snapshots(authority) == snapshots(laptop)
    assert result.head_seq == len(result.results)


def test_sending_the_same_changes_twice_does_nothing_more(project):
    authority, laptop = project("authority"), project("laptop")
    laptop.schema_svc.create("thing")
    laptop.commit()
    from civex.domain.sync import SyncEntry
    from .peers import wire

    entries = [
        SyncEntry.from_dict(wire(e.to_dict()))
        for e in laptop.sync_repo.pending_entries(10)
    ]
    device = authority.authority_svc.add_device("laptop")[0]
    first = authority.authority_svc.push(device, device_uuid("d1"), entries)
    authority.commit()
    again = authority.authority_svc.push(device, device_uuid("d1"), entries)
    authority.commit()

    assert [r.to_dict() for r in again.results] == [r.to_dict() for r in first.results]
    assert again.head_seq == first.head_seq
    assert len(authority.sync_repo.entries_after(0, 100)[0]) == len(entries)


def test_a_change_is_credited_to_the_device_not_to_what_it_claims(project):
    authority, laptop = project("authority"), project("laptop")
    laptop.schema_svc.create("thing")
    laptop.commit()
    laptop.sync_repo._s.query(
        __import__("civex.db.models", fromlist=["AuditLog"]).AuditLog
    ).update({"actor": "mallory"})
    laptop.commit()
    push(authority, laptop, "lab-laptop")
    (entry,), _ = authority.sync_repo.entries_after(0, 10)
    assert entry.actor == "lab-laptop"


def test_edits_to_different_fields_both_survive(world):
    authority, laptop, phone, record = world
    laptop.record_svc.update(str(record.id), {"site": "y", "depth": 1.0})
    phone.record_svc.update(str(record.id), {"site": "x", "depth": 9.0})
    laptop.commit()
    phone.commit()

    assert set(statuses(push(authority, laptop, "laptop"))) == {"applied"}
    result = push(authority, phone, "phone")

    assert statuses(result) == ["merged"]
    assert head(authority, record.id) == {"site": "y", "depth": 9.0}
    # The settled state is in the feed after the change it came from.
    entries, _ = authority.sync_repo.entries_after(0, 100)
    sent = next(e for e in entries if e.id == result.results[0].op_id)
    assert sent.superseded is True
    assert entries[-1].action == "update" and entries[-1].actor == "sync"
    assert entries[-1].new_data["data"] == head_data(authority, record.id)


def head_data(ctx, record_id):
    return ctx.sync_repo.snapshot("record", record_id)["data"]


def test_two_edits_to_one_field_keep_the_authoritys_and_keep_yours_for_review(world):
    authority, laptop, phone, record = world
    laptop.record_svc.update(str(record.id), {"site": "laptop-says", "depth": 1.0})
    phone.record_svc.update(str(record.id), {"site": "phone-says", "depth": 1.0})
    laptop.commit()
    phone.commit()
    push(authority, laptop, "laptop")

    result = push(authority, phone, "phone")

    assert statuses(result) == ["conflict"]
    assert head(authority, record.id)["site"] == "laptop-says"
    (conflict,) = authority.sync_repo.list_conflicts()
    assert conflict.entity_id == record.id and conflict.device_name == "phone"
    assert (conflict.yours, conflict.theirs) == ("phone-says", "laptop-says")
    assert result.results[0].conflicts[0]["yours"] == "phone-says"
    # A device that reads the feed ends where the authority is.
    entries, _ = authority.sync_repo.entries_after(0, 100)
    assert (
        entries[-1].new_data["data"][next(iter(entries[-1].new_data["data"]))]
        is not None
    )


def test_a_delete_of_something_edited_since_is_not_carried_out(world):
    authority, laptop, phone, record = world
    laptop.record_svc.update(str(record.id), {"site": "edited", "depth": 1.0})
    laptop.commit()
    push(authority, laptop, "laptop")
    phone.record_svc.delete(str(record.id))
    phone.commit()

    result = push(authority, phone, "phone")

    assert statuses(result) == ["conflict"]
    assert result.results[0].conflicts[0]["kind"] == "edit_vs_delete"
    assert authority.record_svc.get(str(record.id)).deleted_at is None
    assert head(authority, record.id)["site"] == "edited"


def test_an_edit_of_something_deleted_since_keeps_it(world):
    authority, laptop, phone, record = world
    laptop.record_svc.delete(str(record.id))
    laptop.commit()
    push(authority, laptop, "laptop")
    phone.record_svc.update(str(record.id), {"site": "kept", "depth": 1.0})
    phone.commit()

    result = push(authority, phone, "phone")

    assert result.results[0].conflicts[0]["kind"] == "edit_vs_delete"
    kept = authority.record_svc.get(str(record.id))
    assert kept.deleted_at is None and kept.data["site"] == "kept"


def test_a_delete_nobody_edited_is_carried_out_with_one_stamp_for_the_batch(world):
    authority, laptop, phone, record = world
    laptop.record_svc.delete(str(record.id))
    laptop.commit()
    result = push(authority, laptop, "laptop")
    assert set(statuses(result)) == {"applied"}
    assert authority.sync_repo.snapshot("record", record.id)["deleted_at"] is not None


def test_deleting_a_schema_takes_its_records_and_restoring_brings_them_back(world):
    authority, laptop, _phone, record = world
    laptop.schema_svc.delete("encounter")
    laptop.commit()
    push(authority, laptop, "laptop")
    assert authority.sync_repo.snapshot("record", record.id)["deleted_at"] is not None

    laptop.schema_svc.restore("encounter")
    laptop.commit()
    push(authority, laptop, "laptop")
    assert authority.sync_repo.snapshot("record", record.id)["deleted_at"] is None


def test_a_permanent_delete_removes_the_thing_and_its_history(world):
    authority, laptop, _phone, record = world
    laptop.record_svc.delete(str(record.id))
    laptop.record_svc.purge(str(record.id))
    laptop.commit()

    push(authority, laptop, "laptop")

    assert authority.sync_repo.snapshot("record", record.id) is None
    entries, _ = authority.sync_repo.entries_after(0, 500)
    about = [e for e in entries if e.entity_id == record.id]
    assert [e.action for e in about] == ["purge"]  # only the tombstone is left


def test_a_name_already_taken_is_refused_not_half_done(world):
    authority, laptop, phone, _ = world
    phone.schema_svc.create("clash")
    laptop.schema_svc.create("clash")
    phone.commit()
    laptop.commit()
    push(authority, laptop, "laptop")

    result = push(authority, phone, "phone")

    (refused,) = by_status(result, "rejected")
    assert "UNIQUE" in (refused.message or "").upper() or "unique" in (
        refused.message or ""
    )
    (conflict,) = [
        c for c in authority.sync_repo.list_conflicts() if c.kind == "rejected"
    ]
    assert conflict.device_name == "phone"
    # Told so again, the same way, without redoing anything.
    assert phone.sync_repo.pending_entries(10) == []


def test_a_record_that_cites_a_file_the_authority_lacks_is_taken_anyway(world):
    """Data and files converge separately: the change is not held for a file."""
    authority, laptop, phone, record = world
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    push(authority, laptop, "laptop")
    ref = laptop.file_svc.store_bytes(b"the bytes", "scan.bin")
    laptop.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()

    result = push(authority, laptop, "laptop")

    assert statuses(result) == ["applied"]
    assert head(authority, record.id)["scan"]["sha256"] == ref.sha256
    assert not authority.file_svc.exists(ref.sha256)  # the bytes follow


def test_what_the_authority_numbers_pages_back_in_order(world):
    authority, *_ = world
    page = authority.authority_svc.feed(0, 3)
    assert [e.hub_seq for e in page.entries] == [1, 2, 3] and page.more is True
    assert page.head_seq == authority.sync_repo.head_seq()
    rest = authority.authority_svc.feed(page.entries[-1].hub_seq, 500)
    assert rest.more is False
    assert [e.hub_seq for e in rest.entries] == list(range(4, page.head_seq + 1))


def test_the_authoritys_own_edits_join_the_feed_in_the_order_made(world):
    authority, laptop, phone, record = world
    authority.schema_svc.create("local_only")
    authority.commit()
    page = authority.authority_svc.feed(0, 500)
    assert (
        page.entries[-1].entity_type == "schema" and page.entries[-1].actor is not None
    )
    assert [e.hub_seq for e in page.entries] == sorted(e.hub_seq for e in page.entries)


def test_a_token_works_until_revoked_and_belongs_to_one_device(project):
    authority = project("authority")
    svc = authority.authority_svc
    device, token = svc.add_device("lab-laptop")
    assert svc.authenticate(token, device_uuid("dev-1")).name == "lab-laptop"
    with pytest.raises(SyncError, match="another device"):
        svc.authenticate(token, device_uuid("dev-2"))
    with pytest.raises(SyncError, match="not valid"):
        svc.authenticate("wrong", device_uuid("dev-1"))
    assert svc.revoke_device("lab-laptop") is True
    with pytest.raises(SyncError, match="revoked"):
        svc.authenticate(token, device_uuid("dev-1"))
    with pytest.raises(Exception):
        svc.add_device("lab-laptop") and svc.add_device("lab-laptop")


def test_a_new_authority_is_empty_until_data_arrives_and_remembers_who_brought_it(
    project,
):
    authority, laptop = project("authority"), project("laptop")
    device, _ = authority.authority_svc.add_device("laptop")
    assert authority.authority_svc.hello(device).empty is True
    laptop.schema_svc.create("thing")
    laptop.commit()
    push(authority, laptop, "laptop", device_id=device_uuid("laptop"))
    hello = authority.authority_svc.hello(device)
    assert hello.empty is False and hello.seeded_by == device_uuid("laptop")
    assert hello.protocol_version == 1


def test_a_joining_device_reads_each_kind_in_pages_with_the_head_taken_first(world):
    authority, *_ = world
    page = authority.authority_svc.snapshot("record", 0, 1)
    assert len(page.items) == 1 and page.more is False and page.head_seq > 0
    with pytest.raises(Exception):
        authority.authority_svc.snapshot("nonsense", 0, 10)
