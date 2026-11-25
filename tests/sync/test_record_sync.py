"""Where one record stands with the authority: derived from its own audit
entries, its open conflicts and the files it cites."""

from __future__ import annotations

import pytest

import civex.services.sync_service as sync_service
from civex.domain.sync import SyncError
from civex.testing.peers import build_study, connect, device


def test_a_project_with_no_authority_says_not_connected(project):
    solo = project("solo")
    build_study(solo)
    rec = solo.record_svc.add("study", "encounter", {"site": "a", "depth": 1.0})
    solo.commit()
    assert solo.sync_svc.record_sync(rec.id).state == "not_connected"


def test_an_authority_says_held_here(authority):
    authority.config.sync.serve = True
    assert (
        authority.sync_svc.record_sync(__import__("uuid").uuid4()).state == "held_here"
    )


def test_pending_then_synced(project, authority):
    laptop = device(project, authority, "laptop")
    rec = build_study(laptop)
    connect(laptop)
    assert laptop.sync_svc.record_sync(rec.id).state == "synced"

    laptop.record_svc.update(str(rec.id), {"site": "b", "depth": 2.0})
    laptop.commit()
    waiting = laptop.sync_svc.record_sync(rec.id)
    assert (waiting.state, waiting.pending) == ("pending", 1)

    laptop.sync_svc.sync()
    done = laptop.sync_svc.record_sync(rec.id)
    assert done.state == "synced" and done.pending == 0
    assert done.remote and done.synced_at


def test_an_unfinished_first_upload_is_said(project, authority, monkeypatch):
    monkeypatch.setattr(sync_service, "PUSH_BATCH", 1)
    laptop = device(project, authority, "laptop")
    rec = build_study(laptop)
    original = sync_service.SyncService._seed

    def seed_then_stop(self, transport, *rest, **kw):
        transport.push = lambda entries: (_ for _ in ()).throw(
            SyncError("lost", retryable=True)
        )
        try:
            return original(self, transport, *rest, **kw)
        finally:
            del transport.push

    monkeypatch.setattr(sync_service.SyncService, "_seed", seed_then_stop)
    with pytest.raises(SyncError):
        connect(laptop)
    assert laptop.sync_svc.record_sync(rec.id).state == "first_upload"


def test_a_refused_record_gives_the_authoritys_reason(project, authority):
    laptop = device(project, authority, "laptop")
    laptop.schema_svc.create("call")
    laptop.schema_svc.add_field("call", "annotation", "string")
    laptop.dataset_svc.create("survey")
    laptop.commit()
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    made = laptop.record_svc.add("survey", "call", {"annotation": "M (odd)"})
    laptop.commit()
    phone.schema_svc.update_field(
        "call", "annotation", restrictions={"choices": ["Y", "M", "N"]}
    )
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()

    s = laptop.sync_svc.record_sync(made.id)
    assert s.state == "refused"
    assert "must be one of" in (s.message or "")
    assert s.conflict_id


def test_a_clash_is_in_conflict_with_a_link_to_it(pair):
    laptop, phone, rec = pair
    laptop.record_svc.update(str(rec.id), {"site": "L", "depth": 1.0})
    laptop.commit()
    phone.record_svc.update(str(rec.id), {"site": "P", "depth": 1.0})
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    s = laptop.sync_svc.record_sync(rec.id)
    assert s.state == "conflict" and s.conflict_id


def test_files_sent_and_waiting_are_counted(pair):
    laptop, _, rec = pair
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    ref = laptop.file_svc.store_bytes(b"scan", "s.bin")
    laptop.record_svc.update(
        str(rec.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    laptop.sync_svc.sync()
    s = laptop.sync_svc.record_sync(rec.id)
    assert (s.files, s.files_waiting) == (1, 1)
    laptop.sync_svc.send_files()
    s = laptop.sync_svc.record_sync(rec.id)
    assert (s.files, s.files_waiting) == (1, 0)


def test_the_endpoint_answers_for_a_record(
    client, make_schema, make_collection, make_record
):
    make_schema("doc", fields=[("title", "string")])
    make_collection("study")
    rec = make_record("study", "doc", {"title": "t"})
    body = client.get(f"/api/records/{rec.id}/sync").json()
    assert body["state"] == "not_connected"
    assert client.get("/api/records/nope/sync").status_code == 404


def test_an_unfit_item_is_its_own_state_and_only_offers_to_be_let_go(pair):
    """The shape of a record that went in but breaks a data rule: not a clash,
    not a refusal, and nothing to send again."""
    laptop, _phone, rec = pair
    laptop.sync_svc._repo.add_conflict(
        kind="unfit",
        entity_type="record",
        entity_id=rec.id,
        field=None,
        yours=None,
        theirs=None,
        op_id=None,
        device_name=None,
        message="Required field 'site' is empty",
        code="data",
    )
    laptop.commit()
    s = laptop.sync_svc.record_sync(rec.id)
    assert s.state == "unfit" and s.conflict_id
    assert s.message == "Required field 'site' is empty"
    [row] = [c for c in laptop.sync_svc.conflicts() if c.kind == "unfit"]
    assert row.code == "data" and row.takes == ["theirs"]
