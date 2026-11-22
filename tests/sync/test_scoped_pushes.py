"""What a device's person may not read or write cannot be pushed into, or
taken over by naming another place: the authority judges a push by the same
`Permissions`, and by where the thing is held here."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from civex.context import build_context
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.domain.sync import SyncEntry
from civex.testing import principal, statuses


@pytest.fixture()
def world(project, authority):
    authority.schema_svc.create("encounter")
    authority.schema_svc.add_field("encounter", "site", "string")
    open_ = authority.dataset_svc.create("open")
    vault = authority.dataset_svc.create("vault")
    seen = authority.record_svc.add("open", "encounter", {"site": "open"})
    hidden = authority.record_svc.add("vault", "encounter", {"site": "secret"})
    note = authority.note_svc.add(str(hidden.id), "secret note")
    authority.commit()
    perms = Permissions.of(
        p.READ,
        p.WRITE_RECORDS,
        p.NOTES,
        collections=[open_.id],
        read_collections=[open_.id],
    )
    limited = build_context(dataclasses.replace(authority.project, permissions=perms))
    yield authority, limited, open_, vault, seen, hidden, note
    limited.close()


def _record(authority, dataset, ident=None) -> SyncEntry:
    ident = ident or str(uuid.uuid4())
    return SyncEntry(
        id=uuid.uuid4(),
        action="create",
        entity_type="record",
        entity_id=uuid.UUID(ident),
        old_data=None,
        new_data={
            "id": ident,
            "dataset_id": str(dataset.id),
            "schema_id": str(authority.schema_svc.get("encounter").id),
            "data": {},
            "parent_record_id": None,
            "deleted_at": None,
        },
        timestamp="2026-01-01T00:00:00+00:00",
    )


def test_a_push_into_a_collection_it_may_not_read_is_rejected(world):
    authority, limited, open_, vault, *_ = world
    service = limited.authority_svc
    who = principal(limited, "limited")
    assert statuses(service.push(who, [_record(authority, vault)])) == ["rejected"]
    assert statuses(service.push(who, [_record(authority, open_)])) == ["applied"]


def test_a_record_held_in_a_hidden_collection_cannot_be_taken_by_naming_another(world):
    authority, limited, open_, vault, seen, hidden, note = world
    entry = _record(authority, open_, str(hidden.id))
    result = limited.authority_svc.push(principal(limited, "limited"), [entry])
    assert statuses(result) == ["rejected"]
    authority.commit()
    assert authority.record_svc.get(str(hidden.id)).dataset_id == vault.id


def test_a_hidden_note_cannot_be_moved_onto_a_record_it_may_read(world):
    authority, limited, open_, vault, seen, hidden, note = world
    (snap,) = [
        n
        for n in authority.sync_repo.snapshots_page("note", None, 50)
        if n["id"] == str(note.id)
    ]
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="note",
        entity_id=note.id,
        old_data=None,
        new_data={**snap, "record_id": str(seen.id)},
        timestamp="2026-01-01T00:00:00+00:00",
    )
    result = limited.authority_svc.push(principal(limited, "limited"), [entry])
    assert statuses(result) == ["rejected"]
    authority.commit()
    assert authority.sync_repo.note_record_id(note.id) == hidden.id


def test_a_hidden_collection_cannot_be_changed_by_a_push(world):
    authority, limited, open_, vault, *_ = world
    structure = build_context(
        dataclasses.replace(
            authority.project,
            permissions=Permissions.of(
                p.READ, p.CHANGE_STRUCTURE, p.DELETE, read_collections=[open_.id]
            ),
        )
    )
    try:
        for action in ("update", "delete"):
            entry = SyncEntry(
                id=uuid.uuid4(),
                action=action,
                entity_type="dataset",
                entity_id=vault.id,
                old_data={"id": str(vault.id), "name": "vault"},
                new_data={"id": str(vault.id), "name": "renamed"}
                if action == "update"
                else None,
                timestamp="2026-01-01T00:00:00+00:00",
            )
            result = structure.authority_svc.push(
                principal(structure, "builder"), [entry]
            )
            assert statuses(result) == ["rejected"], action
        # a "create" that names a collection already held is a change to it
        again = dataclasses.replace(
            entry,
            id=uuid.uuid4(),
            action="create",
            old_data=None,
            new_data={"id": str(vault.id), "name": "taken"},
        )
        result = structure.authority_svc.push(principal(structure, "builder"), [again])
        assert statuses(result) == ["rejected"]
        authority.commit()
        assert authority.dataset_svc.get("vault").name == "vault"
    finally:
        structure.close()


def test_a_delta_cannot_move_a_record_into_a_collection_it_may_not_write(world):
    authority, limited, open_, vault, seen, hidden, note = world
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=seen.id,
        old_data=None,
        new_data={"id": str(seen.id), "dataset_id": str(open_.id)},
        timestamp="2026-01-01T00:00:00+00:00",
        delta={"dataset_id": {"before": str(open_.id), "after": str(vault.id)}},
    )
    result = limited.authority_svc.push(principal(limited, "limited"), [entry])
    assert statuses(result) == ["rejected"]
    authority.commit()
    assert authority.record_svc.get(str(seen.id)).dataset_id == open_.id


def test_a_restricted_delete_does_not_leave_a_hidden_reference_dangling(world):
    authority, limited, open_, vault, seen, hidden, note = world
    shared = authority.dataset_svc.create("shared", scope="global")
    authority.schema_svc.add_field(
        "encounter", "friend", "reference", restrictions={"schema": "encounter"}
    )
    target = authority.record_svc.add("shared", "encounter", {"site": "t"})
    authority.record_svc.add(
        "vault", "encounter", {"site": "points", "friend": str(target.id)}
    )
    authority.commit()
    wide = Permissions.of(
        p.READ,
        p.WRITE_RECORDS,
        p.DELETE,
        collections=[open_.id, shared.id],
        read_collections=[open_.id, shared.id],
    )
    ctx = build_context(dataclasses.replace(authority.project, permissions=wide))
    try:
        from civex.domain.exceptions import ValidationError

        for force in (False, True):
            with pytest.raises(ValidationError, match="cannot see"):
                ctx.record_svc.delete(str(target.id), force=force)
    finally:
        ctx.close()
