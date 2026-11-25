"""A busy database is not a broken one; concurrent syncs on one project wait or
defer; files that can't be sent are one log line; and changes refused for
permission are sent again by themselves, with growing gaps, once allowed."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import OperationalError

from civex.domain.sync import REFUSAL_PERMISSION, SyncError, plain_failure
from civex.services import sync_service
from civex.services.sync_lock import SyncBusy, sync_lock
from civex.testing.peers import build_study, connect, device


@pytest.fixture()
def pair(project, authority):
    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    return laptop, record


def _service(ctx):
    """The sync service itself, under the test peer's wrapper."""
    return object.__getattribute__(ctx.sync_svc, "_svc")


def _locked() -> OperationalError:
    return OperationalError(
        "UPDATE audit_log SET device=?",
        (),
        sqlite3.OperationalError("database is locked"),
    )


# -- a busy database ---------------------------------------------------------


def test_a_lock_error_is_transient_and_a_bad_schema_is_not():
    busy = plain_failure(_locked())
    assert busy.retryable and "Another civex process" in str(busy)
    assert "isn't in the shape" not in str(busy)
    assert "database is locked" in busy.detail

    broken = plain_failure(
        OperationalError("SELECT x", (), sqlite3.OperationalError("no such column: x"))
    )
    assert not broken.retryable and "isn't in the shape" in str(broken)


def test_a_busy_database_is_tried_again_and_sync_finishes(pair, monkeypatch):
    laptop, _ = pair
    monkeypatch.setattr(sync_service, "LOCK_RETRY_DELAYS", (0.0, 0.0, 0.0))
    real = _service(laptop)._sync
    failures = [_locked(), _locked()]

    def flaky():
        if failures:
            raise failures.pop()
        return real()

    monkeypatch.setattr(_service(laptop), "_sync", flaky)
    laptop.sync_svc.sync()
    assert laptop.sync_svc.status().last_error is None


def test_a_database_busy_for_good_is_reported_as_transient(pair, monkeypatch):
    laptop, _ = pair
    monkeypatch.setattr(sync_service, "LOCK_RETRY_DELAYS", (0.0,))

    def always():
        raise _locked()

    monkeypatch.setattr(_service(laptop), "_sync", always)
    with pytest.raises(SyncError) as raised:
        laptop.sync_svc.sync()
    assert raised.value.retryable
    assert "isn't in the shape" not in str(raised.value)


def test_a_second_sync_defers_when_the_first_does_not_finish(pair, monkeypatch):
    laptop, _ = pair
    monkeypatch.setattr(sync_service, "LOCK_WAIT_SECONDS", 0.0)
    with sync_lock(laptop.config.civex_dir):
        with pytest.raises(SyncBusy, match="Another sync is already running"):
            laptop.sync_svc.sync()


def test_a_second_sync_waits_for_the_first_to_finish(pair, monkeypatch):
    laptop, _ = pair
    monkeypatch.setattr(sync_service, "LOCK_WAIT_SECONDS", 10.0)
    held = threading.Event()
    release = threading.Event()

    def other_sync():
        with sync_lock(laptop.config.civex_dir):
            held.set()
            release.wait(5)

    t = threading.Thread(target=other_sync)
    t.start()
    held.wait(5)
    threading.Timer(0.6, release.set).start()
    started = time.monotonic()
    laptop.sync_svc.sync()  # waited for the lock, then ran
    assert time.monotonic() - started >= 0.5
    t.join()
    assert laptop.sync_svc.status().last_error is None


# -- the log ------------------------------------------------------------------


def test_files_that_cant_be_sent_are_one_info_line(pair, caplog):
    laptop, record = pair
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    ref = laptop.file_svc.store_bytes(b"scan", "s.bin")
    laptop.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    laptop.file_svc._store.delete(ref.sha256)  # never stored here, as far as it knows
    laptop.commit()
    laptop.sync_svc.sync()
    with caplog.at_level(logging.DEBUG, logger="civex.services.sync_service"):
        report = laptop.sync_svc.send_files()
    infos = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO and " not sent: " in r.getMessage()
    ]
    assert infos == []
    summaries = [r for r in caplog.records if "cannot be read here" in r.getMessage()]
    assert len(summaries) == 1 and summaries[0].levelno == logging.INFO
    assert report.never_stored == [ref.sha256]
    assert "never stored" in summaries[0].getMessage()


# -- refusals for permission --------------------------------------------------


class _Policy:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.asked = 0

    def refuses(self, who, entry):
        if entry.entity_type == "record" and not self.allowed:
            self.asked += 1
            return f"{who.name} may not change records here."
        return None


def _edit(laptop, record, value):
    laptop.record_svc.update(str(record.id), {"site": value, "depth": 1.0})
    laptop.commit()


def _open_refusals(ctx):
    return [c for c in ctx.sync_svc.conflicts() if c.kind == "rejected"]


def _age(ctx, conflict_id, minutes):
    """Pretend the last try was `minutes` ago."""
    from civex.db.models import SyncConflict

    row = ctx.sync_repo._s.get(SyncConflict, conflict_id)
    then = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    row.created_at = then
    if row.retried_at is not None:
        row.retried_at = then
    ctx.sync_repo._s.flush()
    ctx.commit()


def test_a_permission_refusal_carries_a_code(pair, authority, monkeypatch):
    laptop, record = pair
    monkeypatch.setattr(authority.authority_svc, "_policy", _Policy(False))
    _edit(laptop, record, "a")
    laptop.sync_svc.sync()
    (refusal,) = _open_refusals(laptop)
    assert refusal.code == REFUSAL_PERMISSION


def test_a_refused_change_is_sent_again_once_allowed(pair, authority, monkeypatch):
    laptop, record = pair
    policy = _Policy(False)
    monkeypatch.setattr(authority.authority_svc, "_policy", policy)
    _edit(laptop, record, "a")
    report = laptop.sync_svc.sync()
    (refusal,) = _open_refusals(laptop)
    assert report.open_rejected == 1 and report.retried == 0

    # Not due yet: a still-forbidden change is not asked again every sync.
    asked = policy.asked
    laptop.sync_svc.sync()
    assert policy.asked == asked

    policy.allowed = True
    _age(laptop, refusal.id, 20)
    report = laptop.sync_svc.sync()
    assert report.retried == 1 and report.open_rejected == 0
    assert authority.record_svc.get(str(record.id)).data["site"] == "a"
    assert _open_refusals(laptop) == []


def test_a_still_forbidden_change_waits_longer_each_time(pair, authority, monkeypatch):
    laptop, record = pair
    monkeypatch.setattr(authority.authority_svc, "_policy", _Policy(False))
    _edit(laptop, record, "a")
    laptop.sync_svc.sync()
    (refusal,) = _open_refusals(laptop)

    _age(laptop, refusal.id, 20)
    assert laptop.sync_svc.sync().retried == 1  # asked again, refused again
    (refusal,) = _open_refusals(laptop)
    assert refusal.retries == 1 and refusal.code == REFUSAL_PERMISSION

    _age(laptop, refusal.id, 20)  # less than the pause now (an hour)
    assert laptop.sync_svc.sync().retried == 0
    _age(laptop, refusal.id, 70)
    assert laptop.sync_svc.sync().retried == 1


@pytest.mark.usefixtures("rules_refuse")
def test_a_validation_refusal_is_not_sent_again(pair, authority):
    laptop, record = pair
    authority.schema_svc.update_field(
        "encounter", "site", restrictions={"choices": ["only"]}
    )
    authority.commit()
    _edit(laptop, record, "nope")
    laptop.sync_svc.sync()
    (refusal,) = _open_refusals(laptop)
    assert refusal.code != REFUSAL_PERMISSION
    _age(laptop, refusal.id, 60 * 48)
    report = laptop.sync_svc.sync()
    assert report.retried == 0 and report.open_rejected == 1


def test_a_change_is_not_sent_again_for_ever(pair, authority, monkeypatch):
    laptop, record = pair
    monkeypatch.setattr(authority.authority_svc, "_policy", _Policy(False))
    _edit(laptop, record, "a")
    laptop.sync_svc.sync()
    for _ in range(sync_service.MAX_AUTO_RETRIES):
        (refusal,) = _open_refusals(laptop)
        _age(laptop, refusal.id, 60 * 24 * 3)
        assert laptop.sync_svc.sync().retried == 1
    (refusal,) = _open_refusals(laptop)
    _age(laptop, refusal.id, 60 * 24 * 3)
    assert laptop.sync_svc.sync().retried == 0
