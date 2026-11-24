"""Round-3 regressions for scoped sync: entries stored before the upgrade carry a
claimed collection, a record that left a newly readable collection under a new
parent, and fetching history in steps across a long hidden run."""

from __future__ import annotations

import uuid

import pytest

from civex.domain.sync import OpResult, SyncEntry
from civex.services import sync_authority, sync_service
from civex.testing import connect, device, snapshots

from .test_scoped_devices import (  # noqa: F401
    SECRET,
    Study,
    held,
    study,
    text_of,
)


def _legacy_watermark(authority) -> None:
    """Everything stored so far was stored before entries were stamped."""
    repo = authority.sync_repo
    repo._meta_row().placed_from = repo.head_seq()
    authority.commit()


def _history_text(ctx) -> str:
    return str([e.to_dict() for e in ctx.sync_repo.entries_after(0, 5000)[0]])


def test_a_legacy_claimed_entry_of_a_record_now_out_of_sight_is_not_sent(study: Study):
    authority, limited = study.authority, study.limited
    seen = study.open_records[0]
    base = authority.authority_svc._applier.head("record", seen.id)
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    study.sync(limited)
    key = next(k for k, v in base["data"].items() if isinstance(v, str))
    secret_state = {**base, "data": {**base["data"], key: f"{SECRET}-LEGACY"}}
    repo = authority.sync_repo
    claimed = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=seen.id,
        old_data=dict(base),
        new_data=secret_state,
        timestamp="2026-01-02T00:00:00+00:00",
    )
    seq = repo.next_hub_seq()
    repo.insert_entry(claimed, hub_seq=seq, apply_state="superseded")
    repo.save_op(claimed, OpResult(claimed.id, "merged", None, [], seq), None, "full")
    settled = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=seen.id,
        old_data={**base, "dataset_id": str(study.vault.id)},
        new_data={**secret_state, "dataset_id": str(study.vault.id)},
        timestamp="2026-01-02T00:00:00+00:00",
    )
    repo.insert_entry(settled, hub_seq=repo.next_hub_seq())
    authority.commit()
    _legacy_watermark(authority)
    page = study.only_open.authority_svc.feed(0, 500)
    assert "LEGACY" not in str([e.to_dict() for e in page.entries])
    study.sync(limited)
    assert "LEGACY" not in text_of(limited) and "LEGACY" not in _history_text(limited)
    late = device(study.project, study.only_open, "late")
    connect(late)
    for _ in range(20):
        if late.sync_svc.fetch_history():
            break
    late.commit()
    assert "LEGACY" not in _history_text(late) and "LEGACY" not in text_of(late)


def test_a_legacy_delta_claiming_the_old_collection_is_not_sent(study: Study):
    authority, limited = study.authority, study.limited
    seen = study.open_records[0]
    base = authority.authority_svc._applier.head("record", seen.id)
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    study.sync(limited)
    key = next(k for k, v in base["data"].items() if isinstance(v, str))
    legacy = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=seen.id,
        old_data={"id": str(seen.id), "dataset_id": str(study.open.id)},
        new_data={"id": str(seen.id), "dataset_id": str(study.open.id)},
        delta={
            f"data.{key}": {"before": base["data"][key], "after": f"{SECRET}-LDELTA"}
        },
        timestamp="2026-01-02T00:00:00+00:00",
    )
    repo = authority.sync_repo
    repo.insert_entry(legacy, hub_seq=repo.next_hub_seq())
    authority.commit()
    _legacy_watermark(authority)
    study.sync(limited)
    assert "LDELTA" not in text_of(limited) and "LDELTA" not in _history_text(limited)
    assert limited.sync_repo.meta().cursor == authority.sync_repo.head_seq()


def test_a_legacy_entry_of_a_record_still_in_sight_is_sent_as_before(study: Study):
    authority, limited = study.authority, study.limited
    seen = study.open_records[0]
    authority.record_svc.update(str(seen.id), {"site": "edited in open"})
    authority.commit()
    study.sync(study.full)
    _legacy_watermark(authority)
    study.sync(limited)
    assert "edited in open" in text_of(limited)


def test_a_record_that_left_a_newly_readable_collection_for_a_new_parent_arrives(
    study: Study, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sync_service, "SNAPSHOT_PAGE", 2)
    authority, limited = study.authority, study.limited
    authority.schema_svc.create("kid", parent="encounter")
    authority.schema_svc.add_field("kid", "site", "string")
    authority.commit()
    pv = authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} PV"})
    r = authority.record_svc.add(
        "vault", "kid", {"site": "R"}, parent_record_id=str(pv.id)
    )
    authority.commit()
    study.sync(limited)
    # after the device's cursor: a new parent in open, and R moved under it
    pn = authority.record_svc.add("open", "encounter", {"site": "PN"})
    authority.commit()
    authority.record_svc.move("open", str(pn.id), ids=[str(r.id)])
    authority.commit()
    study.widen(study.open.id, study.vault.id)
    study.sync(limited, study.full)
    assert str(r.id) in held(limited, "record")
    assert str(pn.id) in held(limited, "record")
    assert sorted(held(limited, "record")) == sorted(held(study.full, "record"))
    study.sync(limited)
    assert sorted(held(limited, "record")) == sorted(held(study.full, "record"))
    assert limited.sync_repo.meta().cursor == authority.sync_repo.head_seq()


def test_fetching_history_in_single_steps_gets_past_a_long_hidden_run(
    study: Study, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sync_authority, "FEED_SCAN_MAX", 12)
    monkeypatch.setattr(sync_authority, "FEED_MAX", 4)
    monkeypatch.setattr(sync_service, "FEED_PAGE", 4)
    authority = study.authority
    for i in range(60):
        authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} {i}"})
    visible = authority.record_svc.add("open", "encounter", {"site": "after the run"})
    for i in range(5):
        authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} b{i}"})
    authority.commit()
    late = device(study.project, study.only_open, "late")
    connect(late)
    done = False
    for _ in range(60):
        if late.sync_svc.fetch_history(pages=1):
            done = True
            break
        late.commit()
    late.commit()
    assert done
    assert late.sync_repo.meta().history_from is None
    assert str(visible.id) in _history_text(late)
    assert SECRET not in _history_text(late)


def test_a_small_page_size_does_not_multiply_the_work(study: Study, monkeypatch):
    from sqlalchemy import event

    monkeypatch.setattr(sync_authority, "FEED_SCAN_MAX", 40)
    authority = study.authority
    for i in range(60):
        authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} {i}"})
    authority.commit()
    service = study.only_open.authority_svc
    service.feed(0, 1)  # numbers what the authority made
    engine = authority.sync_repo._s.get_bind()
    seen: list[str] = []

    def count(conn, cursor, statement, *args):
        if "FROM audit_log" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        service.feed(0, 1)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(seen) <= 6, len(seen)


def test_a_left_after_before_the_history_floor_is_raised_to_it(study: Study):
    service = study.only_open.authority_svc
    authority = study.authority
    authority.sync_repo._meta_row().feed_floor = 50
    authority.commit()
    page = service.snapshot("record", None, 50, study.open.id, 0)
    assert page.items == []  # nothing left `open` after the floor
    assert snapshots(authority)  # (the authority itself is untouched)
