"""What a person may do, said once: a vocabulary of actions over the project
or named collections, asked by the services and by the sync authority alike."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from civex.domain import permissions as p
from civex.domain.exceptions import NotAllowedError
from civex.domain.permissions import Permissions
from civex.domain.sync import SyncEntry

C1, C2 = uuid.uuid4(), uuid.uuid4()


def _entry(kind: str, action: str, snapshot: dict | None = None) -> SyncEntry:
    return SyncEntry(
        id=uuid.uuid4(),
        action=action,
        entity_type=kind,
        entity_id=uuid.uuid4(),
        old_data=snapshot if action in ("delete", "purge") else None,
        new_data=snapshot if action not in ("delete", "purge") else None,
        timestamp="2026-01-01T00:00:00+00:00",
    )


def test_the_local_user_may_do_everything_everywhere():
    assert p.EVERYTHING.can(p.DELETE)
    assert p.EVERYTHING.can(p.WRITE_RECORDS, C1)
    p.EVERYTHING.require(p.MANAGE_MEMBERS)  # nothing raised
    assert p.EVERYTHING.refuses(None, _entry("schema", "update")) is None


def test_an_action_can_be_limited_to_collections():
    writer = Permissions.of(p.READ, p.WRITE_RECORDS, collections=[C1])
    assert writer.can(p.READ)  # reading is always project-wide
    assert writer.can(p.WRITE_RECORDS, C1)
    assert not writer.can(p.WRITE_RECORDS, C2)
    assert not writer.can(p.WRITE_RECORDS)  # anywhere? no
    assert not writer.can(p.DELETE, C1)
    with pytest.raises(NotAllowedError, match="You may not add, change"):
        writer.require(p.WRITE_RECORDS, C2)
    with pytest.raises(NotAllowedError, match="You may not delete"):
        writer.require(p.DELETE, C1)


def test_it_round_trips_as_data():
    writer = Permissions.of(p.READ, p.WRITE_RECORDS, collections=[C1])
    again = Permissions.from_dict(writer.to_dict())
    assert again == writer
    assert writer.to_dict()["actions"]["write_records"] == [f"collection:{C1}"]
    assert Permissions.nothing().to_dict() == {"actions": {}}


def test_a_pushed_change_is_judged_by_the_same_rule():
    """The authority asks the permissions as its policy: a record change is a
    write (or a delete) in its collection; the rest is structure."""
    writer = Permissions.of(p.READ, p.WRITE_RECORDS, collections=[C1])

    class Who:
        name = "laptop"
        person = "Dr Example"

    mine = {"id": str(uuid.uuid4()), "dataset_id": str(C1)}
    theirs = {"id": str(uuid.uuid4()), "dataset_id": str(C2)}
    assert writer.refuses(Who(), _entry("record", "create", mine)) is None
    assert writer.refuses(Who(), _entry("record", "update", mine)) is None
    assert writer.refuses(Who(), _entry("record", "create", theirs)) == (
        "Dr Example may not add, change and restore records, and save filters "
        "and exports here."
    )
    assert "may not delete" in writer.refuses(Who(), _entry("record", "delete", mine))
    assert "may not change kinds" in writer.refuses(Who(), _entry("field", "update"))
    assert "may not delete" in writer.refuses(Who(), _entry("dataset", "delete"))
    assert writer.refuses(Who(), _entry("view", "create")) is None  # a writer somewhere
    reader = Permissions.of(p.READ)
    assert "may not save" in reader.refuses(Who(), _entry("view", "create"))
    assert p.action_for(_entry("schema", "purge")) == (p.DELETE, None)
    assert p.action_for(_entry("view", "update")) == (p.VIEWS, p.ANYWHERE)
    assert p.action_for(_entry("record", "restore", mine)) == (p.WRITE_RECORDS, str(C1))


def test_without_carves_collections_out_of_a_wider_grant():
    writer = Permissions.of(p.READ, p.WRITE_RECORDS).without([p.WRITE_RECORDS], [C1])
    assert not writer.can(p.WRITE_RECORDS, C1)
    assert writer.can(p.WRITE_RECORDS, C2)  # and any collection made later
    assert writer.can(p.WRITE_RECORDS)  # "somewhere" is untouched
    assert writer.can(p.READ, C1)
    with pytest.raises(NotAllowedError):
        writer.require(p.WRITE_RECORDS, C1)


def test_denied_collections_refuse_pushed_changes_and_round_trip():
    writer = Permissions.of(p.READ, p.WRITE_RECORDS).without([p.WRITE_RECORDS], [C1])
    mine = {"id": str(uuid.uuid4()), "dataset_id": str(C1)}

    class Who:
        name = "laptop"

    assert writer.refuses(Who(), _entry("record", "create", mine)) is not None
    assert Permissions.from_dict(writer.to_dict()) == writer
    assert Permissions.from_dict({"actions": {"read": ["project"]}}).denied == {}


# -- C3: the wider vocabulary ----------------------------------------------------


def test_manage_files_is_both_adding_and_deleting():
    both = Permissions.of(p.READ, p.MANAGE_FILES)
    assert (
        both.can(p.ADD_FILES) and both.can(p.DELETE_FILES) and both.can(p.MANAGE_FILES)
    )
    assert both.to_dict()["actions"].keys() >= {p.ADD_FILES, p.DELETE_FILES}
    assert p.MANAGE_FILES not in both.to_dict()["actions"]
    adder = Permissions.of(p.READ, p.ADD_FILES)
    assert adder.can(p.ADD_FILES) and not adder.can(p.DELETE_FILES)
    assert not adder.can(p.MANAGE_FILES)  # the alias asks for both
    only_here = Permissions.of(p.READ, p.MANAGE_FILES, collections=[C1])
    assert only_here.can(p.ADD_FILES, C1) and not only_here.can(p.DELETE_FILES, C2)
    denied = Permissions.of(p.READ, p.MANAGE_FILES).without([p.MANAGE_FILES], [C1])
    assert not denied.can(p.ADD_FILES, C1) and denied.can(p.DELETE_FILES, C2)


def test_every_action_can_be_limited_to_collections():
    for action in p.ACTIONS:
        if action == p.READ:
            continue
        scoped = Permissions.of(p.READ, action, collections=[C1])
        assert scoped.can(action, C1) and not scoped.can(action, C2), action
        assert not scoped.can(action) and scoped.can_somewhere(action), action


def test_read_can_be_limited_and_what_is_unread_is_not_seen():
    everyone = Permissions.of(p.READ)
    assert everyone.read_scope().unrestricted
    only = Permissions.of(p.READ, read_collections=[C1])
    scope = only.read_scope()
    assert scope.sees(C1) and not scope.sees(C2) and not scope.unrestricted
    assert only.can(p.READ, C1) and not only.can(p.READ, C2)
    assert not Permissions.nothing().read_scope().sees(C1)
    all_but = Permissions.of(p.READ).without([p.READ], [C1])
    assert not all_but.read_scope().sees(C1) and all_but.read_scope().sees(C2)
    assert all_but.read_scope().sees(uuid.uuid4())  # a collection made later


def test_notes_and_views_follow_writing_unless_the_host_says_otherwise():
    writer = Permissions.of(p.READ, p.WRITE_RECORDS, collections=[C1])
    assert writer.can(p.NOTES, C1) and writer.can_somewhere(p.VIEWS)
    carved = Permissions.of(p.READ, p.WRITE_RECORDS).without([p.WRITE_RECORDS], [C1])
    assert not carved.can(p.NOTES, C1) and carved.can(p.NOTES, C2)  # denials follow too
    silent = Permissions.of(p.READ, p.WRITE_RECORDS).lacking(p.NOTES, p.VIEWS)
    assert not silent.can(p.NOTES) and not silent.can_somewhere(p.VIEWS)
    assert silent.can(p.WRITE_RECORDS)
    stated = Permissions.of(p.READ, p.WRITE_RECORDS, p.NOTES, collections=[C1])
    assert stated.can(p.NOTES, C1) and stated.can_somewhere(p.VIEWS)
    just_notes = Permissions.of(p.READ, p.NOTES, collections=[C2])
    assert just_notes.can(p.NOTES, C2) and not just_notes.can(p.WRITE_RECORDS, C2)
    assert Permissions.everything().can(p.MANAGE_DEVICES)
    assert not Permissions.of(p.READ, p.WRITE_RECORDS).can_somewhere(p.MANAGE_DEVICES)


def test_a_pushed_change_needs_to_read_where_it_writes_and_the_files_rights():
    class Who:
        name = "laptop"

    only = Permissions.of(
        p.READ, p.WRITE_RECORDS, collections=[C1], read_collections=[C1, C2]
    )
    elsewhere = Permissions.of(p.READ, p.WRITE_RECORDS, read_collections=[C1])
    mine = {"id": str(uuid.uuid4()), "dataset_id": str(C1)}
    theirs = {"id": str(uuid.uuid4()), "dataset_id": str(C2)}
    assert only.refuses(Who(), _entry("record", "create", mine)) is None
    assert elsewhere.refuses(Who(), _entry("record", "create", mine)) is None
    assert elsewhere.refuses(Who(), _entry("record", "create", theirs))  # unseen
    # A change that names a hidden collection as where the record was
    moved = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=uuid.uuid4(),
        old_data=theirs,
        new_data=mine,
        timestamp="2026-01-01T00:00:00+00:00",
    )
    assert elsewhere.refuses(Who(), moved)
    sha = "a" * 64
    with_file = dict(mine, data={"f": {"sha256": sha, "filename": "x", "size": 1}})
    writer = Permissions.of(p.READ, p.WRITE_RECORDS)
    assert "add files" in writer.refuses(Who(), _entry("record", "create", with_file))
    assert (
        writer.lacking(p.NOTES).refuses(Who(), _entry("record", "create", mine)) is None
    )
    adder = Permissions.of(p.READ, p.WRITE_RECORDS, p.ADD_FILES)
    assert adder.refuses(Who(), _entry("record", "create", with_file)) is None
    # letting a file go is a right of its own
    let_go = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=uuid.uuid4(),
        old_data=with_file,
        new_data=mine,
        timestamp="2026-01-01T00:00:00+00:00",
    )
    assert "delete files" in adder.refuses(Who(), let_go)
    assert (
        Permissions.of(p.READ, p.WRITE_RECORDS, p.MANAGE_FILES).refuses(Who(), let_go)
        is None
    )


def test_notes_are_judged_in_their_records_collection():
    class Who:
        name = "laptop"

    note = {"id": str(uuid.uuid4()), "dataset_id": str(C1)}
    elsewhere = {"id": str(uuid.uuid4()), "dataset_id": str(C2)}
    notes_in_c1 = Permissions.of(p.READ, p.NOTES, collections=[C1])
    assert notes_in_c1.refuses(Who(), _entry("note", "create", note)) is None
    assert "notes" in notes_in_c1.refuses(Who(), _entry("note", "create", elsewhere))
    assert p.action_for(_entry("note", "create", note)) == (p.NOTES, str(C1))


def test_a_collection_one_cannot_read_cannot_be_changed_or_deleted_by_a_push():
    class Who:
        name = "laptop"

    builder = Permissions.of(
        p.READ, p.CHANGE_STRUCTURE, p.DELETE, read_collections=[C1]
    )
    seen = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="dataset",
        entity_id=C1,
        old_data=None,
        new_data={"id": str(C1)},
        timestamp="2026-01-01T00:00:00+00:00",
    )
    assert builder.refuses(Who(), seen) is None
    hidden = dataclasses.replace(seen, entity_id=C2, new_data={"id": str(C2)})
    assert builder.refuses(Who(), hidden)
    assert builder.refuses(Who(), dataclasses.replace(hidden, action="delete"))
    made = dataclasses.replace(hidden, action="create")
    assert (
        builder.refuses(Who(), made) is None
    )  # a new collection is a structure matter


def test_a_collection_id_spelled_another_way_is_the_same_collection():
    class Who:
        name = "laptop"

    writer = Permissions.of(p.READ, p.WRITE_RECORDS).without([p.WRITE_RECORDS], [C1])
    for spelling in (str(C1).upper(), C1.hex, f"{{{C1}}}"):
        snap = {"id": str(uuid.uuid4()), "dataset_id": spelling}
        assert writer.refuses(Who(), _entry("record", "create", snap)), spelling
    hidden = Permissions.of(p.READ).without([p.READ], [C1])
    assert not hidden.can(p.READ, C1.hex) and not hidden.read_scope().sees(C1.hex)


def test_a_move_in_a_delta_is_judged_at_its_destination():
    class Who:
        name = "laptop"

    writer = Permissions.of(p.READ, p.WRITE_RECORDS, collections=[C1])
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=uuid.uuid4(),
        old_data=None,
        new_data={"id": str(uuid.uuid4()), "dataset_id": str(C1)},
        timestamp="2026-01-01T00:00:00+00:00",
        delta={"dataset_id": {"before": str(C1), "after": str(C2)}},
    )
    assert "add, change" in writer.refuses(Who(), entry)
    assert p.entry_collections(entry) == (str(C1), str(C2))


def test_files_cited_by_a_create_are_added_whatever_old_data_says():
    class Who:
        name = "laptop"

    sha = "b" * 64
    held = {
        "id": str(uuid.uuid4()),
        "dataset_id": str(C1),
        "data": {"f": {"sha256": sha}},
    }
    forged = SyncEntry(
        id=uuid.uuid4(),
        action="create",
        entity_type="record",
        entity_id=uuid.uuid4(),
        old_data=held,
        new_data=held,
        timestamp="2026-01-01T00:00:00+00:00",
    )
    assert "add files" in Permissions.of(p.READ, p.WRITE_RECORDS).refuses(Who(), forged)
    whole = dataclasses.replace(
        forged,
        action="update",
        old_data=None,
        new_data={"id": held["id"], "dataset_id": str(C1)},
        delta={"data": {"before": {}, "after": {"f": {"sha256": sha}}}},
    )
    assert "add files" in Permissions.of(p.READ, p.WRITE_RECORDS).refuses(Who(), whole)


def test_a_denial_civex_cannot_read_closes_read_rather_than_dropping_it():
    odd = Permissions(
        {p.READ: frozenset({p.PROJECT})}, {p.READ: frozenset({"collection:nonsense"})}
    )
    assert not odd.read_scope().sees(C1) and not odd.read_scope().sees(C2)
