"""What a person may do, said once: a vocabulary of actions over the project
or named collections, asked by the services and by the sync authority alike."""

from __future__ import annotations

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
    assert "may not add" in reader.refuses(Who(), _entry("view", "create"))
    assert p.action_for(_entry("schema", "purge")) == (p.DELETE, None)
    assert p.action_for(_entry("view", "update")) == (p.WRITE_RECORDS, p.ANYWHERE)
    assert p.action_for(_entry("record", "restore", mine)) == (p.WRITE_RECORDS, str(C1))
