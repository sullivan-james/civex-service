"""Follow-ups from the review of the scoped-sync fixes."""

from __future__ import annotations

import uuid

from civex.testing import principal  # noqa: F401
from civex.testing.peers import read_earlier

from .test_scoped_devices import (  # noqa: F401
    SECRET,
    Study,
    held,
    reads,
    scoped,
    study,
    text_of,
)


def test_a_collection_that_came_in_the_feed_is_not_read_again(study: Study):
    authority, limited = study.authority, study.limited
    made = authority.dataset_svc.create("later")
    authority.record_svc.add("later", "encounter", {"site": "in later"})
    authority.commit()
    study.widen(study.open.id, made.id)
    study.sync(limited)
    assert "in later" in text_of(limited)
    calls = limited._holder["inner"].calls
    calls.clear()
    study.sync(limited)
    assert "snapshot" not in calls


def test_a_hidden_collection_is_asked_about_like_one_that_is_not_there(study: Study):
    service = study.only_open.authority_svc
    hidden = service.snapshot("record", None, 50, study.vault.id, 0)
    plain = service.snapshot("record", None, 50, study.vault.id)
    absent = service.snapshot("record", None, 50, uuid.uuid4(), 0)
    assert hidden.items == plain.items == absent.items == []
    assert hidden.more is absent.more is False


def test_a_note_made_before_its_record_moved_is_judged_where_the_record_was(
    study: Study,
):
    authority = study.authority
    mover = study.vault_records[0]  # has the vault's note, made while hidden
    second = authority.note_svc.add(str(mover.id), f"{SECRET} second")
    authority.record_svc.move("open", ids=[str(mover.id)])
    authority.commit()
    page = study.only_open.authority_svc.feed(0, 500)
    notes = [e for e in page.entries if e.entity_type == "note"]
    # what was said while the record was in the vault reaches the device only
    # as the record's whole creation with its notes, never as the changes
    assert all(e.action == "create" for e in notes)
    assert all(e.id != second.id for e in notes)


def test_a_kind_the_shaper_does_not_know_is_not_sent(study: Study):
    from sqlalchemy import text

    authority = study.authority
    head = authority.sync_repo.head_seq() + 1000
    authority._session.execute(
        text(
            "INSERT INTO audit_log (id, action, entity_type, entity_id, timestamp, "
            "sync_state, apply_state, hub_seq) VALUES "
            "('00000000-0000-0000-0000-0000000000aa', 'create', 'mystery', "
            "'00000000-0000-0000-0000-0000000000bb', '2026-01-01', 'synced', "
            "'applied', :seq)"
        ),
        {"seq": head},
    )
    authority.commit()
    limited = study.only_open.authority_svc.feed(0, 500)
    assert all(e.entity_type != "mystery" for e in limited.entries)
    full = authority.authority_svc.feed(0, 500)
    assert any(e.entity_type == "mystery" for e in full.entries)


def test_a_stale_claim_by_a_full_device_does_not_leak_into_a_limited_feed(
    study: Study,
):
    from civex.domain.sync import SyncEntry

    authority = study.authority
    seen = study.open_records[0]
    base = authority.authority_svc._applier.head("record", seen.id)
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    key = next(k for k, v in base["data"].items() if isinstance(v, str))
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=seen.id,
        old_data=dict(base),
        new_data={**base, "data": {**base["data"], key: f"{SECRET}-EDIT"}},
        timestamp="2026-01-02T00:00:00+00:00",
    )
    authority.authority_svc.push(principal(authority, "full"), [entry])
    authority.commit()
    page = study.only_open.authority_svc.feed(0, 500)
    assert f"{SECRET}-EDIT" not in str([e.to_dict() for e in page.entries])
    assert not any(
        e.entity_id == seen.id and e.action == "update" for e in page.entries
    )


def test_a_superseded_move_still_reaches_a_device_as_its_creation_or_removal():
    from civex.domain.permissions import ReadScope
    from civex.domain.sync import SyncEntry
    from civex.services.sync_scope import FeedShaper

    here, there, record = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    whole = {"id": str(record), "dataset_id": str(here), "data": {}}

    def move(src, dst) -> SyncEntry:
        return SyncEntry(
            id=uuid.uuid4(),
            action="update",
            entity_type="record",
            entity_id=record,
            old_data={"id": str(record), "dataset_id": str(src)},
            new_data={"id": str(record), "dataset_id": str(dst)},
            timestamp="2026-01-01T00:00:00+00:00",
            hub_seq=5,
            superseded=True,
        )

    shaper = FeedShaper(
        ReadScope(only=frozenset({here})),
        lambda _r: here,
        lambda _r: whole,
        lambda _r: [],
        lambda ids: {},
    )
    (made,) = shaper.shape([move(there, here)])
    assert made.action == "create" and made.superseded is False
    (gone,) = shaper.shape([move(here, there)])
    assert gone.action == "purge" and gone.superseded is False


def test_history_before_joining_is_fetched_across_a_long_hidden_run(
    study: Study, monkeypatch
):
    from civex.services import sync_authority
    from civex.testing import connect, device

    monkeypatch.setattr(sync_authority, "FEED_SCAN_MAX", 12)
    authority = study.authority
    for i in range(40):
        authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} {i}"})
    authority.commit()
    late = device(study.project, study.only_open, "late")
    connect(late)
    entries, _ = authority.sync_repo.entries_after(0, 1000)
    mine = [
        e
        for e in entries
        if e.entity_type == "record"
        and (e.new_data or {}).get("dataset_id") == str(study.open.id)
    ]
    assert mine
    got = {e.id for e in read_earlier(late)}
    assert all(e.id in got for e in mine)
