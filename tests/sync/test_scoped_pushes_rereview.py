"""Regressions from the second review: where a pushed record is *settled* (under
its parent) is what is judged and stored, and refusals tell a hidden record from
an absent one in no way the authority can help."""

from __future__ import annotations

import dataclasses
import uuid

from civex.context import build_context
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.domain.sync import SyncEntry
from civex.testing import principal, statuses

from .test_scoped_pushes_review import _create, world  # noqa: F401


def _answer(result) -> dict:
    d = result.results[0].to_dict()
    d.pop("op_id", None)
    d.pop("hub_seq", None)
    return d


def _update(authority, record, site: str, **claims) -> SyncEntry:
    base = authority.authority_svc._applier.head("record", record.id)
    key = next(k for k, v in base["data"].items() if isinstance(v, str))
    new = {**base, "data": {**base["data"], key: site}, **claims}
    return SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=uuid.UUID(str(base["id"])),
        old_data=dict(base),
        new_data=new,
        timestamp="2026-01-02T00:00:00+00:00",
    )


# -- 1: parent placement ------------------------------------------------------------


def test_a_child_cannot_be_placed_into_a_collection_the_device_may_not_write(world):
    authority, _, open_, vault, seen, hidden, *_ = world
    perms = Permissions.of(
        p.READ, p.WRITE_RECORDS, read_collections=None, collections=[open_.id]
    )
    device = build_context(dataclasses.replace(authority.project, permissions=perms))
    try:
        entry = _create(authority, open_, {"site": "child"})
        entry.new_data["parent_record_id"] = str(hidden.id)
        result = device.authority_svc.push(principal(device, "writer"), [entry])
        assert statuses(result) == ["rejected"]
        assert result.results[0].conflicts[0]["code"] == "permission"
        device.commit()
    finally:
        device.close()
    assert authority.authority_svc._applier.head("record", entry.entity_id) is None


def test_a_hidden_parent_is_refused_like_an_absent_one_and_never_errors(world):
    authority, limited, open_, vault, seen, hidden, *_ = world
    who = principal(limited, "limited")
    answers = []
    for parent in (str(hidden.id), str(uuid.uuid4())):
        entry = _create(authority, open_, {"site": "child"})
        entry.new_data["parent_record_id"] = parent
        result = limited.authority_svc.push(who, [entry])
        assert statuses(result) == ["rejected"]
        answers.append(_answer(result))
        limited.commit()
    assert answers[0] == answers[1]
    # and a device that sees everything gets a clean refusal, not an error at commit
    entry = _create(authority, open_, {"site": "child"})
    entry.new_data["parent_record_id"] = str(uuid.uuid4())
    result = authority.authority_svc.push(principal(authority, "full"), [entry])
    assert statuses(result) == ["rejected"]
    authority.commit()


# -- 2: the stored entry names where the authority had the record ---------------------


def test_a_stale_claim_of_where_a_record_is_is_not_what_is_stored(world):
    authority, limited, open_, vault, seen, hidden, *_ = world
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    stale = _update(authority, seen, "TOPSECRET-EDIT", dataset_id=str(open_.id))
    stale.old_data["dataset_id"] = str(open_.id)
    full = principal(authority, "full")
    authority.authority_svc.push(full, [stale])
    authority.commit()
    entries, _ = authority.sync_repo.entries_after(0, 500)
    mine = [e for e in entries if e.id == stale.id]
    assert mine
    for e in mine:
        assert (e.new_data or {}).get("dataset_id") == str(vault.id)
        assert (e.old_data or {}).get("dataset_id") == str(vault.id)


def test_a_delta_that_claims_another_collection_is_stored_where_it_happened(world):
    authority, limited, open_, vault, seen, hidden, *_ = world
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    base = authority.authority_svc._applier.head("record", seen.id)
    key = next(k for k, v in base["data"].items() if isinstance(v, str))
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=seen.id,
        old_data={"id": str(seen.id), "dataset_id": str(open_.id)},
        new_data={"id": str(seen.id), "dataset_id": str(open_.id)},
        delta={f"data.{key}": {"before": base["data"][key], "after": "edited"}},
        timestamp="2026-01-02T00:00:00+00:00",
    )
    authority.authority_svc.push(principal(authority, "full"), [entry])
    authority.commit()
    entries, _ = authority.sync_repo.entries_after(0, 500)
    (stored,) = [e for e in entries if e.id == entry.id]
    assert stored.new_data["dataset_id"] == str(vault.id)
    assert stored.old_data["dataset_id"] == str(vault.id)
    assert "dataset_id" not in (stored.delta or {})


# -- 4: changing or deleting a hidden id is answered as one that is not there --------


def test_changing_a_hidden_record_is_answered_as_changing_an_absent_one(world):
    authority, limited, open_, vault, seen, hidden, *_ = world
    who = principal(limited, "limited")
    # (claiming the collection it may write to, as anyone probing would)
    base = authority.authority_svc._applier.head("record", seen.id)
    for action in ("update", "delete"):
        got = []
        for rid in (str(hidden.id), str(uuid.uuid4())):
            old = {**base, "id": rid}
            entry = SyncEntry(
                id=uuid.uuid4(),
                action=action,
                entity_type="record",
                entity_id=uuid.UUID(rid),
                old_data=old,
                new_data=None
                if action == "delete"
                else {**old, "data": dict(old["data"])},
                timestamp="2026-01-02T00:00:00+00:00",
            )
            got.append(_answer(limited.authority_svc.push(who, [entry])))
            limited.commit()
        assert got[0] == got[1], (action, got)


def test_deleting_purging_or_restoring_a_hidden_id_is_answered_as_an_absent_one(world):
    authority, _, open_, vault, seen, hidden, *_ = world
    perms = Permissions.of(
        p.READ,
        p.WRITE_RECORDS,
        p.DELETE,
        collections=[open_.id],
        read_collections=[open_.id],
    )
    device = build_context(dataclasses.replace(authority.project, permissions=perms))
    try:
        who = principal(device, "deleter")
        base = authority.authority_svc._applier.head("record", seen.id)
        for action in ("delete", "purge", "restore"):
            got = []
            for rid in (str(hidden.id), str(uuid.uuid4())):
                old = {**base, "id": rid}
                entry = SyncEntry(
                    id=uuid.uuid4(),
                    action=action,
                    entity_type="record",
                    entity_id=uuid.UUID(rid),
                    old_data=old,
                    new_data=None if action != "restore" else dict(old),
                    timestamp="2026-01-02T00:00:00+00:00",
                )
                got.append(_answer(device.authority_svc.push(who, [entry])))
                device.commit()
            assert got[0] == got[1], (action, got)
            assert got[0]["status"] == "rejected"
    finally:
        device.close()
    # nothing of the hidden record was touched
    authority.commit()
    assert authority.record_svc.get(str(hidden.id)).deleted_at is None


def test_a_hidden_record_updated_with_a_hidden_file_is_answered_like_an_absent_one(
    world,
):
    authority, limited, open_, vault, seen, hidden, secret, plain = world
    who = principal(limited, "limited")
    got = []
    for rid in (str(hidden.id), str(uuid.uuid4())):
        base = authority.authority_svc._applier.head("record", seen.id)
        scan = next(k for k, v in base["data"].items() if isinstance(v, dict))
        old = {**base, "id": rid}
        new = {**old, "data": {**base["data"], scan: secret.to_dict()}}
        entry = SyncEntry(
            id=uuid.uuid4(),
            action="update",
            entity_type="record",
            entity_id=uuid.UUID(rid),
            old_data=old,
            new_data=new,
            timestamp="2026-01-02T00:00:00+00:00",
        )
        got.append(_answer(limited.authority_svc.push(who, [entry])))
        limited.commit()
    assert got[0] == got[1]


def test_an_unrelated_edit_to_a_child_whose_parent_is_out_of_sight_is_taken(world):
    authority, limited, open_, vault, seen, hidden, *_ = world
    # a visible child that sits under a record the device cannot see now
    child = _create(authority, open_, {"site": "child"})
    child.new_data["parent_record_id"] = str(seen.id)
    assert statuses(
        authority.authority_svc.push(principal(authority, "full"), [child])
    ) == ["applied"]
    authority.commit()
    head = authority.authority_svc._applier.head("record", child.entity_id)
    assert head["parent_record_id"] == str(seen.id)
    edit = _update(authority, type("R", (), {"id": child.entity_id}), "edited")
    result = limited.authority_svc.push(principal(limited, "limited"), [edit])
    assert statuses(result) == ["applied"]
