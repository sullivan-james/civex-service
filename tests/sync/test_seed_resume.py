"""A first upload (seed) that was interrupted is finished by the next sync of
any kind, whatever a pull did to the cursor meanwhile, and is shown meanwhile."""

from __future__ import annotations

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

    def seed_then_stop(self, transport, *rest):
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
            return original(self, transport, *rest)
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
