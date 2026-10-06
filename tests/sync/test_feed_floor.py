"""A device that fell behind further than the authority keeps history copies the
project again, instead of silently skipping what the feed no longer holds; what
it made meanwhile is still sent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .peers import snapshots
from .test_convergence import differences


def _prune_everything(authority) -> None:
    authority.audit_svc.prune(datetime.now(timezone.utc) + timedelta(days=1), False)
    authority.commit()


def test_a_device_behind_the_pruned_history_copies_again(pair, authority):
    laptop, phone, record = pair
    gone = laptop.record_svc.add("study", "encounter", {"site": "doomed", "depth": 0.0})
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    # The phone is away. Meanwhile the laptop changes and removes things...
    laptop.record_svc.update(str(record.id), {"site": "changed", "depth": 1.0})
    added = laptop.record_svc.add("study", "encounter", {"site": "new", "depth": 2.0})
    laptop.record_svc.delete(str(gone.id))
    laptop.record_svc.purge(str(gone.id))
    laptop.commit()
    laptop.sync_svc.sync()
    # ...and the authority cleans up its history past where the phone read.
    _prune_everything(authority)
    assert authority.sync_repo.meta().feed_floor > phone.sync_repo.meta().cursor

    # The phone made a change of its own while away.
    mine = phone.record_svc.add(
        "study", "encounter", {"site": "from phone", "depth": 3.0}
    )
    phone.commit()

    phone.sync_svc.sync()
    laptop.sync_svc.sync()

    expected = snapshots(authority)
    assert differences(expected, snapshots(phone)) == []
    ids = {r["id"] for r in expected["record"]}
    assert str(added.id) in ids and str(mine.id) in ids and str(gone.id) not in ids
    assert phone.sync_repo.meta().cursor == authority.sync_repo.head_seq()


def test_a_device_that_kept_up_is_not_copied_again(pair, authority):
    laptop, phone, _ = pair
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    _prune_everything(authority)
    calls = phone._holder["inner"].calls
    before = calls.count("snapshot")
    phone.sync_svc.sync()
    assert calls.count("snapshot") == before
