"""A first upload (seed) that was interrupted is finished by the next sync of
any kind, whatever a pull did to the cursor meanwhile, and is shown meanwhile."""

from __future__ import annotations

import uuid

import pytest

import civex.services.sync_service as sync_service
from civex.db.models import Record
from civex.domain.sync import SyncError
from civex.testing.peers import build_study, connect, device


def _records(ctx) -> set[str]:
    return {str(r.id) for r in ctx.sync_repo._s.query(Record).all()}


def _interrupted_laptop(project, authority, monkeypatch, pushes=2):
    monkeypatch.setattr(sync_service, "PUSH_BATCH", 1)
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    for i in range(5):
        laptop.record_svc.add("study", "encounter", {"site": f"s{i}", "depth": 1.0})
    laptop.commit()
    original = sync_service.SyncService._seed
    broke = []

    def seed_then_stop(self, transport, *rest, **kw):
        real = transport.push
        calls = 0

        def push(entries):
            nonlocal calls
            if calls >= pushes and not broke:
                broke.append(1)
                raise SyncError("connection lost", retryable=True)
            calls += 1
            return real(entries)

        transport.push = push
        try:
            return original(self, transport, *rest, **kw)
        finally:
            del transport.push

    monkeypatch.setattr(sync_service.SyncService, "_seed", seed_then_stop)
    with pytest.raises(SyncError):
        connect(laptop)
    monkeypatch.setattr(sync_service.SyncService, "_seed", original)
    return laptop


def test_an_interrupted_seed_is_shown_and_its_error_kept(
    project, authority, monkeypatch
):
    laptop = _interrupted_laptop(project, authority, monkeypatch)
    status = laptop.sync_svc.status()
    assert status.seeding > 0
    assert status.pending == 0
    assert status.last_error and "connection lost" in status.last_error
    assert _records(authority) < _records(laptop)


def test_the_next_ordinary_sync_finishes_it(project, authority, monkeypatch):
    laptop = _interrupted_laptop(project, authority, monkeypatch)
    seen = []
    laptop.sync_svc.sync(progress=seen.append)
    assert seen
    assert laptop.sync_svc.status().seeding == 0
    assert _records(authority) == _records(laptop)
    again = laptop.sync_svc.sync()
    assert (again.pushed, again.pulled) == (0, 0)
    assert _records(authority) == _records(laptop)


def test_a_pull_that_moved_the_cursor_does_not_strand_the_seed(
    project, authority, monkeypatch
):
    """The exact field case: the feed was pulled after the interruption."""
    laptop = _interrupted_laptop(project, authority, monkeypatch)
    assert laptop.sync_svc.pull() > 0 or laptop.sync_repo.meta().cursor > 0
    assert laptop.sync_repo.meta().cursor > 0
    assert laptop.sync_svc.status().seeding > 0

    laptop.sync_svc.sync()

    assert laptop.sync_svc.status().seeding == 0
    assert _records(authority) == _records(laptop)
    count = authority.sync_repo._s.query(Record).count()
    laptop.sync_svc.sync()
    assert authority.sync_repo._s.query(Record).count() == count


def test_connecting_again_resumes_too(project, authority, monkeypatch):
    laptop = _interrupted_laptop(project, authority, monkeypatch)
    laptop.sync_svc.pull()
    assert connect(laptop) == "seeded"
    assert laptop.sync_svc.status().seeding == 0
    assert _records(authority) == _records(laptop)


def test_changes_made_after_the_interruption_arrive_once(
    project, authority, monkeypatch
):
    laptop = _interrupted_laptop(project, authority, monkeypatch)
    first = sorted(_records(laptop))[0]
    laptop.record_svc.update(first, {"site": "edited", "depth": 2.0})
    added = laptop.record_svc.add("study", "encounter", {"site": "new", "depth": 3.0})
    laptop.commit()
    assert laptop.sync_svc.status().pending > 0

    laptop.sync_svc.sync()
    laptop.sync_svc.sync()

    status = laptop.sync_svc.status()
    assert (status.seeding, status.pending, status.open_conflicts) == (0, 0, 0)
    assert _records(authority) == _records(laptop)
    site = next(
        f for f in authority.schema_svc.get("encounter").fields if f.name == "site"
    )
    assert authority.sync_repo.snapshot("record", uuid.UUID(first))["data"][
        str(site.id)
    ] == ("edited")
    assert authority.sync_repo.snapshot("record", added.id)["data"][str(site.id)] == (
        "new"
    )


def test_a_resume_leaves_other_devices_work_alone(project, authority, monkeypatch):
    """What a second device did meanwhile is pulled (not skipped by moving the
    cursor on), and the resumed upload sends only its own things, so nothing of
    the other device's is sent back as if made here."""
    laptop = _interrupted_laptop(project, authority, monkeypatch, pushes=5)
    phone = device(project, authority, "phone")
    connect(phone)
    theirs = phone.record_svc.add("study", "encounter", {"site": "p", "depth": 9.0})
    phone.commit()
    phone.sync_svc.sync()

    laptop.sync_svc.sync()
    phone.record_svc.update(str(theirs.id), {"site": "p2", "depth": 9.0})
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()

    assert str(theirs.id) in _records(laptop)
    assert laptop.sync_svc.status().open_conflicts == 0
    assert laptop.sync_svc.status().seeding == 0


def test_a_release_made_over_an_unfinished_seed_arrives_with_every_record(
    project, authority, monkeypatch
):
    """The field case: a release is made while the first upload is stranded; it
    goes as an ordinary change, and the resumed seed brings the records it
    counts, and its bundle file is uploaded."""
    laptop = _interrupted_laptop(project, authority, monkeypatch)
    laptop.release_svc.create("v1", "A release")
    laptop.commit()

    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()

    assert laptop.sync_svc.status().seeding == 0
    assert _records(authority) == _records(laptop)
    made = authority.release_svc.get("v1")
    assert made is not None
    assert authority.file_svc.exists(made.bundle_sha256)


def test_a_resume_after_the_device_id_changed_is_still_a_seed(
    project, authority, monkeypatch
):
    """The history is not flipped to raw pending changes because this
    computer's device id is not the one that began the upload."""
    laptop = _interrupted_laptop(project, authority, monkeypatch)
    before = laptop.sync_svc.status().seeding
    check = sync_service.SyncService._check_protocol

    def as_if_another_began_it(self, hello):
        hello.seeded_by = str(uuid.uuid4())
        return check(self, hello)

    monkeypatch.setattr(
        sync_service.SyncService, "_check_protocol", as_if_another_began_it
    )
    laptop.sync_svc.sync()
    s = laptop.sync_svc.status()
    assert (s.seeding, s.pending, s.open_conflicts) == (0, 0, 0)
    assert before > 0
    assert _records(authority) == _records(laptop)


def test_retention_keeps_what_a_first_upload_has_still_to_send(
    project, authority, monkeypatch
):
    from datetime import datetime, timedelta, timezone

    laptop = _interrupted_laptop(project, authority, monkeypatch)
    seeding = laptop.sync_repo.count_seeding()
    laptop.audit_svc.prune(datetime.now(timezone.utc) + timedelta(days=1), True)
    laptop.commit()
    assert laptop.sync_repo.count_seeding() == seeding


def test_connecting_again_after_a_pull_sends_only_what_was_set_aside(
    project, authority, monkeypatch
):
    laptop = _interrupted_laptop(project, authority, monkeypatch, pushes=5)
    phone = device(project, authority, "phone")
    connect(phone)
    theirs = phone.record_svc.add("study", "encounter", {"site": "p", "depth": 9.0})
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.pull()
    phone.record_svc.update(str(theirs.id), {"site": "p2", "depth": 9.0})
    phone.commit()
    phone.sync_svc.sync()

    assert connect(laptop) == "seeded"
    laptop.sync_svc.sync()
    assert laptop.sync_svc.status().open_conflicts == 0
    assert laptop.sync_svc.status().seeding == 0
    assert _records(authority) == _records(laptop)
