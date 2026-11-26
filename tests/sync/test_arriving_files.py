"""A file cited by a record that was just pushed, whose bytes the sending
device hasn't uploaded yet, is `arriving`; only after a wait is it `missing`."""

from __future__ import annotations

from civex.domain import quality
from civex.domain.query import RecordQuery


def _cite(laptop, record, content: bytes = b"the scan"):
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    ref = laptop.file_svc.store_bytes(content, "scan.bin")
    laptop.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    return ref


def _lines(ctx):
    report = ctx.quality_svc.check(RecordQuery())
    return [i for k in report.kinds for i in k.issues]


def test_a_file_not_uploaded_yet_is_not_reported_missing(pair, authority):
    laptop, _, record = pair
    _cite(laptop, record)
    laptop.sync_svc.sync()
    issues = _lines(authority)
    assert not [i for i in issues if i.issue == quality.MISSING_FILE]


def _with_old_receipt(authority, days: int):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from civex.db.models import SyncOp

    authority.sync_repo._s.execute(
        update(SyncOp).values(
            received_at=datetime.now(timezone.utc) - timedelta(days=days)
        )
    )
    authority.commit()


def test_a_file_cited_by_a_pushed_record_is_arriving(pair, authority):
    laptop, _, record = pair
    ref = _cite(laptop, record)
    laptop.sync_svc.sync()
    loc = authority.record_svc.get(str(record.id)).data["scan"]["location"]
    assert loc["state"] == "arriving"
    assert "Uploading" in loc["reason"]

    laptop.sync_svc.send_files()
    authority.sync_repo._s.expire_all()
    loc = authority.record_svc.get(str(record.id)).data["scan"]["location"]
    assert loc["state"] != "arriving" and loc["volume"] is not None
    assert not [i for i in _lines(authority) if i.issue == quality.MISSING_FILE]
    assert ref.sha256


def test_it_is_missing_once_the_wait_has_passed(pair, authority):
    laptop, _, record = pair
    _cite(laptop, record)
    laptop.sync_svc.sync()
    _with_old_receipt(authority, days=2)
    missing = [i for i in _lines(authority) if i.issue == quality.MISSING_FILE]
    assert len(missing) == 1


def test_the_wait_is_configurable(pair, authority):
    laptop, _, record = pair
    _cite(laptop, record)
    laptop.sync_svc.sync()
    authority.config.sync.arriving_hours = 0
    missing = [i for i in _lines(authority) if i.issue == quality.MISSING_FILE]
    assert len(missing) == 1
    authority.config.sync.arriving_hours = 72
    _with_old_receipt(authority, days=2)
    assert not [i for i in _lines(authority) if i.issue == quality.MISSING_FILE]


def test_a_file_nobody_pushed_is_still_missing(authority):
    from civex.testing import build_study

    record = build_study(authority)
    authority.schema_svc.add_field("encounter", "scan", "file")
    authority.commit()
    ghost = {"sha256": "ab" * 32, "filename": "lost.bin", "size": 3}
    authority.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": ghost}
    )
    authority.commit()
    missing = [i for i in _lines(authority) if i.issue == quality.MISSING_FILE]
    assert len(missing) == 1


def test_the_files_list_says_arriving_then_missing(pair, authority):
    from civex.domain.file_access import PLACE_ARRIVING, PLACE_MISSING, FileSelection

    laptop, _, record = pair
    _cite(laptop, record)
    laptop.sync_svc.sync()
    sel = FileSelection(
        query=RecordQuery(), record_ids=None, fields=["scan"], base=None
    )
    svc = authority.file_access_svc
    assert [i.state for i in svc.listing(sel, place=PLACE_ARRIVING).items] == [
        "arriving"
    ]
    assert not svc.listing(sel, place=PLACE_MISSING).items
    _with_old_receipt(authority, days=2)
    assert not svc.listing(sel, place=PLACE_ARRIVING).items
    assert len(svc.listing(sel, place=PLACE_MISSING).items) == 1


def test_an_unrelated_edit_does_not_make_an_old_missing_file_arrive(pair, authority):
    laptop, _, record = pair
    _cite(laptop, record)
    laptop.sync_svc.sync()
    _with_old_receipt(authority, days=2)
    laptop.record_svc.update(
        str(record.id), {"site": "y", "depth": 2.0, "scan": _scan(laptop, record)}
    )
    laptop.commit()
    laptop.sync_svc.sync()  # lately received, but it did not cite the file
    missing = [i for i in _lines(authority) if i.issue == quality.MISSING_FILE]
    assert len(missing) == 1


def test_a_refused_change_does_not_make_a_file_arrive(pair, authority):
    from sqlalchemy import update

    from civex.db.models import SyncOp

    laptop, _, record = pair
    _cite(laptop, record)
    laptop.sync_svc.sync()
    authority.sync_repo._s.execute(update(SyncOp).values(status="refused"))
    authority.commit()
    missing = [i for i in _lines(authority) if i.issue == quality.MISSING_FILE]
    assert len(missing) == 1


def _scan(laptop, record):
    return laptop.record_svc.get(str(record.id)).data["scan"]


def test_the_inventory_counts_arriving_and_missing_apart(pair, authority):
    """What a host's Files page leads with: how many files are stored, arriving
    (within `sync.arriving_hours`) and missing, and which records cite each."""
    from civex.domain.file_access import FileSelection

    laptop, _, record = pair
    _cite(laptop, record, b"one")
    laptop.sync_svc.sync()
    sel = FileSelection(
        query=RecordQuery(), record_ids=None, fields=["scan"], base=None
    )
    svc = authority.file_access_svc

    def kinds():
        return {p.kind: p.files for p in svc.listing(sel).summary}

    assert kinds() == {"arriving": 1}
    listed = svc.listing(sel)
    (item,) = listed.items
    assert [u.record_id for u in listed.uses[f"{item.sha256}@"]] == [str(record.id)]
    _with_old_receipt(authority, days=2)
    assert kinds() == {"missing": 1}
    laptop.sync_svc.send_files()
    authority.sync_repo._s.expire_all()
    assert kinds() == {"drive": 1}
