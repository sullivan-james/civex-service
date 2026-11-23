"""A device acts for a person who may not read every collection: the authority
never sends it a hidden collection's data (feed, snapshot, files, counts), takes
pushes only into collections it may read and write, tells it when it has been
given more so it catches up, and stops sending when it is given less."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from civex.context import build_context
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.domain.sync import PROTOCOL_MAX, SyncEntry
from civex.testing import connect, device, principal, push, snapshots, statuses

SECRET = "TOPSECRET"


def scoped(authority, perms: Permissions):
    """A context on the same project for a caller with these permissions: what
    the host's resolver would build for a device's request."""
    return build_context(dataclasses.replace(authority.project, permissions=perms))


def reads(*collections) -> Permissions:
    return Permissions.of(
        p.READ,
        p.WRITE_RECORDS,
        p.NOTES,
        collections=collections,
        read_collections=collections,
    )


class Study:
    """An authority holding `open` and `vault`, a full device and a limited one
    (that sees `open` only)."""

    def __init__(self, project, authority) -> None:
        self.authority = authority
        authority.schema_svc.create("encounter")
        authority.schema_svc.add_field("encounter", "site", "string")
        authority.schema_svc.add_field("encounter", "depth", "float")
        self.open = authority.dataset_svc.create("open")
        self.vault = authority.dataset_svc.create("vault")
        self.open_records = [
            authority.record_svc.add("open", "encounter", {"site": f"open {i}"})
            for i in range(2)
        ]
        self.vault_records = [
            authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} {i}"})
            for i in range(3)
        ]
        authority.note_svc.add(str(self.open_records[0].id), "plain note")
        authority.note_svc.add(str(self.vault_records[0].id), f"{SECRET} note")
        authority.commit()
        self.only_open = scoped(authority, reads(self.open.id))
        self.full = device(project, authority, "full")
        self.limited = device(project, self.only_open, "limited")
        self.project = project
        connect(self.full)
        connect(self.limited)

    def widen(self, *collections) -> None:
        """The limited device's person is given these collections."""
        self.retarget(scoped(self.authority, reads(*collections)))

    def retarget(self, authority) -> None:
        self.limited._holder["inner"]._authority = authority
        self.only_open = authority

    def sync(self, *devices) -> None:
        for d in devices:
            d.sync_svc.sync()
            d.commit()
        self.authority.commit()


def held(ctx, kind: str) -> set[str]:
    return {s["id"] for s in snapshots(ctx)[kind]}


def text_of(ctx) -> str:
    return str(snapshots(ctx))


@pytest.fixture()
def study(project, authority) -> Study:
    return Study(project, authority)


def test_a_device_is_only_ever_given_what_its_person_may_read(study: Study):
    limited, full = study.limited, study.full
    assert SECRET not in text_of(limited)
    assert held(limited, "record") == {str(r.id) for r in study.open_records}
    assert held(limited, "dataset") == {str(study.open.id)}
    assert len(held(limited, "note")) == 1
    # the full device has it all
    assert len(held(full, "record")) == 5 and len(held(full, "dataset")) == 2


def test_two_devices_with_different_scopes_get_different_feeds(study: Study):
    authority = study.authority
    authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} new"})
    authority.record_svc.add("open", "encounter", {"site": "open new"})
    authority.commit()
    study.sync(study.limited, study.full)
    assert SECRET not in text_of(study.limited)
    assert len(held(study.limited, "record")) == 3
    assert len(held(study.full, "record")) == 7
    # nothing hidden is left for the device to be re-sent: its cursor is at the head
    assert study.limited.sync_repo.meta().cursor == authority.sync_repo.head_seq()


def test_an_unseen_run_of_changes_does_not_hold_the_device_in_place(study: Study):
    authority = study.authority
    for i in range(30):
        authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} {i}"})
    authority.commit()
    study.sync(study.limited)
    assert study.limited.sync_repo.meta().cursor == authority.sync_repo.head_seq()
    service = study.only_open.authority_svc
    page = service.feed(study.limited.sync_repo.meta().cursor - 5, 200)
    assert page.entries == []  # nothing for it, and nothing leaks through the page
    assert page.through == authority.sync_repo.head_seq()


def test_the_feed_carries_no_hidden_ids_or_counts(study: Study):
    authority = study.authority
    authority.record_svc.update(
        str(study.vault_records[0].id), {"site": f"{SECRET} changed"}
    )
    authority.commit()
    service = study.only_open.authority_svc
    page = service.feed(0, 500)
    blob = str([e.to_dict() for e in page.entries])
    assert SECRET not in blob
    for r in study.vault_records:
        assert str(r.id) not in blob
    assert str(study.vault.id) not in blob
    hello = service.hello(principal(study.only_open, "limited"), PROTOCOL_MAX)
    assert hello.counts["record"] == 2 and hello.counts["dataset"] == 1
    assert [c["id"] for c in hello.readable] == [str(study.open.id)]
    assert hello.empty is False


def test_a_caller_who_sees_nothing_is_not_an_empty_authority(study: Study):
    nothing = scoped(study.authority, Permissions.of(p.READ, read_collections=[]))
    hello = nothing.authority_svc.hello(principal(nothing, "blind"), PROTOCOL_MAX)
    assert hello.empty is False and hello.counts["record"] == 0
    assert hello.readable == []


def test_pushes_may_touch_only_permitted_collections(study: Study):
    service = study.only_open.authority_svc
    who = principal(study.only_open, "limited")

    def record(dataset, ident=None, site="x"):
        ident = ident or str(uuid.uuid4())
        return SyncEntry(
            id=uuid.uuid4(),
            action="create",
            entity_type="record",
            entity_id=uuid.UUID(ident),
            old_data=None,
            new_data={
                "id": ident,
                "dataset_id": str(dataset),
                "schema_id": str(study.authority.schema_svc.get("encounter").id),
                "data": {},
                "parent_record_id": None,
                "deleted_at": None,
            },
            timestamp="2026-01-01T00:00:00+00:00",
        )

    hidden = service.push(who, [record(study.vault.id)])
    assert statuses(hidden) == ["rejected"]
    # naming a collection it may write to for a record that is held in one it may not
    taken_over = service.push(
        who, [record(study.open.id, str(study.vault_records[0].id))]
    )
    assert statuses(taken_over) == ["rejected"]
    study.authority.commit()
    still = study.authority.record_svc.get(str(study.vault_records[0].id))
    assert still.dataset_id == study.vault.id
    ok = service.push(who, [record(study.open.id)])
    assert statuses(ok) == ["applied"]


def test_a_record_cannot_point_at_a_hidden_one(study: Study):
    authority = study.authority
    authority.schema_svc.add_field(
        "encounter", "friend", "reference", restrictions={"schema": "encounter"}
    )
    authority.commit()
    friend = authority.schema_svc.get("encounter")
    fid = next(f.id for f in friend.fields if f.name == "friend")
    study.only_open = scoped(authority, reads(study.open.id))
    service = study.only_open.authority_svc
    ident = str(uuid.uuid4())
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="create",
        entity_type="record",
        entity_id=uuid.UUID(ident),
        old_data=None,
        new_data={
            "id": ident,
            "dataset_id": str(study.open.id),
            "schema_id": str(friend.id),
            "data": {str(fid): str(study.vault_records[0].id)},
            "parent_record_id": None,
            "deleted_at": None,
        },
        timestamp="2026-01-01T00:00:00+00:00",
    )
    result = service.push(principal(study.only_open, "limited"), [entry])
    assert statuses(result) == ["rejected"]


def test_widening_access_backfills_what_the_device_never_had(study: Study):
    authority, limited = study.authority, study.limited
    # while it could not see the vault, more happened there
    authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} later"})
    authority.commit()
    study.sync(limited)
    assert SECRET not in text_of(limited)
    study.widen(study.open.id, study.vault.id)
    study.sync(limited, study.full)
    assert held(limited, "record") == held(study.full, "record")
    assert held(limited, "dataset") == held(study.full, "dataset")
    assert held(limited, "note") == held(study.full, "note")
    # and from then on it is simply in the feed
    authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} after"})
    authority.commit()
    study.sync(limited, study.full)
    assert held(limited, "record") == held(study.full, "record")


def test_narrowing_stops_delivery_but_cannot_take_back_what_it_holds(study: Study):
    authority, limited = study.authority, study.limited
    study.widen(study.open.id, study.vault.id)
    study.sync(limited)
    assert len(held(limited, "record")) == 5
    study.retarget(scoped(authority, reads(study.open.id)))
    authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} after"})
    authority.commit()
    study.sync(limited)
    assert len(held(limited, "record")) == 5  # nothing new, nothing taken back
    assert any(SECRET in str(s) for s in snapshots(limited)["record"])


def test_given_access_back_it_catches_up_on_the_gap_and_drops_what_went(study: Study):
    authority, limited = study.authority, study.limited
    study.widen(study.open.id, study.vault.id)
    study.sync(limited)
    study.retarget(scoped(authority, reads(study.open.id)))
    study.sync(limited)
    # while it was away: one record added, one removed for good
    gone = study.vault_records[1]
    authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} gap"})
    authority.record_svc.delete(str(gone.id))
    authority.record_svc.purge(str(gone.id))
    authority.commit()
    study.widen(study.open.id, study.vault.id)
    study.sync(limited, study.full)
    assert held(limited, "record") == held(study.full, "record")
    assert str(gone.id) not in held(limited, "record")


def test_a_record_moved_out_of_sight_is_removed_and_one_moved_in_is_given_whole(
    study: Study,
):
    authority, limited = study.authority, study.limited
    mover = study.open_records[1]
    authority.record_svc.move("vault", ids=[str(mover.id)])
    inbound = study.vault_records[0]  # has the vault's note
    authority.record_svc.move("open", ids=[str(inbound.id)])
    authority.commit()
    study.sync(limited)
    mine = held(limited, "record")
    assert str(mover.id) not in mine
    assert str(inbound.id) in mine
    assert any("TOPSECRET note" in str(n) for n in snapshots(limited)["note"])
    # whole: the data came with it, not only the change of collection
    (got,) = [r for r in snapshots(limited)["record"] if r["id"] == str(inbound.id)]
    assert got["data"] and got["dataset_id"] == str(study.open.id)


def test_a_protocol_4_device_is_filtered_too_but_is_not_told_what_it_can_read(
    study: Study,
):
    service = study.only_open.authority_svc
    who = principal(study.only_open, "limited")
    hello = service.hello(who, 4)
    assert hello.readable is None and "readable" not in hello.to_dict()
    assert SECRET not in str([e.to_dict() for e in service.feed(0, 500).entries])
    assert SECRET not in str(service.snapshot("record", None, 500).items)


def test_a_snapshot_page_is_full_however_much_is_hidden(study: Study):
    authority = study.authority
    for i in range(10):
        authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} {i}"})
    authority.commit()
    page = study.only_open.authority_svc.snapshot("record", None, 2)
    assert len(page.items) == 2 and page.more is False
    one = study.only_open.authority_svc.snapshot("record", None, 1)
    assert len(one.items) == 1 and one.more is True
    named = study.only_open.authority_svc.snapshot("record", None, 50, study.vault.id)
    assert named.items == []  # asking for a hidden collection by name gets nothing


def test_what_the_full_device_pushes_reaches_the_limited_one_only_in_its_scope(
    study: Study,
):
    full, limited = study.full, study.limited
    full.record_svc.add("vault", "encounter", {"site": f"{SECRET} from full"})
    full.record_svc.add("open", "encounter", {"site": "from full"})
    full.commit()
    study.sync(full, limited)
    assert SECRET not in text_of(limited)
    assert any(r["data"] for r in snapshots(limited)["record"])
    assert len(held(limited, "record")) == 3


def test_a_hidden_collections_file_is_not_downloadable_by_a_device(study: Study):
    authority = study.authority
    blob = authority.file_svc.store_bytes(f"{SECRET} bytes".encode(), "v.bin")
    authority.schema_svc.add_field("encounter", "scan", "file")
    authority.record_svc.update(
        str(study.vault_records[0].id), {"site": "x", "scan": blob.to_dict()}
    )
    authority.commit()
    from civex.domain.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        study.only_open.file_svc.check_readable(blob.sha256)
    authority.file_svc.check_readable(blob.sha256)


def test_a_device_cannot_move_a_hidden_note_onto_a_record_it_may_read(study: Study):
    authority = study.authority
    (hidden_note,) = [
        n
        for n in authority.sync_repo.snapshots_page("note", None, 50)
        if n["record_id"] == str(study.vault_records[0].id)
    ]
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="note",
        entity_id=uuid.UUID(hidden_note["id"]),
        old_data=None,
        new_data={**hidden_note, "record_id": str(study.open_records[0].id)},
        timestamp="2026-01-01T00:00:00+00:00",
    )
    result = study.only_open.authority_svc.push(
        principal(study.only_open, "limited"), [entry]
    )
    assert statuses(result) == ["rejected"]
    authority.commit()
    assert authority.sync_repo.note_record_id(uuid.UUID(hidden_note["id"])) == (
        study.vault_records[0].id
    )


def test_what_was_said_about_a_record_while_hidden_is_not_replayed_when_it_comes_in(
    study: Study,
):
    authority, limited = study.authority, study.limited
    record = study.vault_records[1]
    first = authority.note_svc.add(str(record.id), f"{SECRET} while hidden")
    authority.note_svc.edit(str(first.id), f"{SECRET} edited while hidden")
    authority.commit()
    study.sync(limited)  # nothing of it yet
    assert SECRET not in text_of(limited)
    authority.record_svc.move("open", ids=[str(record.id)])
    authority.note_svc.add(str(record.id), "said once it was in")
    authority.commit()
    study.sync(limited)
    notes = snapshots(limited)["note"]
    on_it = [n for n in notes if n["record_id"] == str(record.id)]
    assert len(on_it) == 2  # each once, as they are now, no stale copies
    assert str(record.id) in held(limited, "record")
