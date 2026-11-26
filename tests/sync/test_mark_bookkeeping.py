"""What a device writes down after a push, and when its own changes come back
in the feed: written together, with the same rows as one change at a time."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from civex.db.models import AuditLog
from civex.domain.exceptions import NotFoundError
from civex.domain.sync import OpResult
from civex.repositories.local.sync_repo import LocalSyncRepository


def _repo(ctx) -> LocalSyncRepository:
    return LocalSyncRepository(ctx._session)


def _rows(ctx, n: int) -> list[uuid.UUID]:
    ctx.commit()
    ctx._session.query(AuditLog).delete()
    ids = [uuid.UUID(int=100 + i) for i in range(n)]
    for i in ids:
        ctx._session.add(
            AuditLog(
                id=i,
                action="delete",
                entity_type="record",
                entity_id=uuid.uuid4(),
                old_data={},
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                sync_state="pending",
            )
        )
    ctx.commit()
    return ids


def _state(ctx):
    ctx._session.expire_all()
    return [
        (r.id, r.sync_state, r.hub_seq, r.apply_state, r.device)
        for r in ctx._session.query(AuditLog).order_by(AuditLog.id)
    ]


def _old_mark_sent(repo: LocalSyncRepository, results: list[OpResult]) -> None:
    for result in results:
        row = repo._s.get(AuditLog, result.op_id)
        if row is None:
            continue
        if result.status == "rejected":
            row.sync_state = "rejected"
        elif result.status != "deferred":
            row.sync_state = "synced"
            if result.hub_seq is not None:
                row.hub_seq = result.hub_seq
            if result.status in ("merged", "conflict"):
                row.apply_state = "superseded"
    repo._s.flush()


def _answers(ids: list[uuid.UUID]) -> list[OpResult]:
    unknown = uuid.UUID(int=999_999)
    out = [
        OpResult(ids[0], "applied", hub_seq=11),
        OpResult(ids[1], "rejected"),
        OpResult(ids[2], "deferred"),
        OpResult(ids[3], "merged", hub_seq=12),
        OpResult(ids[4], "conflict"),
        OpResult(unknown, "applied", hub_seq=13),  # not held here: skipped
        # answered twice: each answer counts, the later one winning
        OpResult(ids[5], "applied", hub_seq=21),
        OpResult(ids[5], "merged"),
        OpResult(ids[6], "rejected"),
        OpResult(ids[6], "applied", hub_seq=22),
        OpResult(ids[7], "applied", hub_seq=23),
        OpResult(ids[7], "deferred"),
    ]
    return out


def test_mark_sent_matches_one_at_a_time_row_for_row(project):
    new, old = project("new"), project("old")
    # (the same ids in both)
    ids = _rows(new, 10)
    assert _rows(old, 10) == ids
    answers = _answers(ids)
    _repo(new).mark_sent(answers)  # unknown id: skipped, no error
    new.commit()
    _old_mark_sent(_repo(old), answers)
    old.commit()
    assert _state(new) == _state(old)


def test_mark_seqs_matches_mark_seq_row_for_row(project):
    new, old = project("new"), project("old")
    ids = _rows(new, 8)
    assert _rows(old, 8) == ids
    for ctx in (new, old):
        _repo(ctx).mark_sent([OpResult(ids[0], "rejected")])  # not pending
        ctx.commit()
    items = [
        (ids[0], 5, "phone"),
        (ids[1], 6, None),
        (ids[2], 7, "laptop"),
        (ids[2], 8, None),  # twice: the later number, the device kept
        (ids[3], 9, "phone"),
    ]
    _repo(new).mark_seqs(items)
    new.commit()
    for entry_id, seq, device in items:
        _repo(old).mark_seq(entry_id, seq, device)
    old.commit()
    assert _state(new) == _state(old)
    assert _repo(new).mark_seqs([]) is None


def _statements(ctx, work) -> list[str]:
    seen: list[str] = []
    engine = ctx._session.get_bind()

    def count(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        work()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return seen


def test_a_page_of_answers_and_numbers_is_a_few_statements(project):
    ctx = project("a")
    ids = _rows(ctx, 200)
    repo = _repo(ctx)
    answers = [OpResult(i, "applied", hub_seq=n + 1) for n, i in enumerate(ids)]
    sent = _statements(ctx, lambda: repo.mark_sent(answers))
    assert len(sent) <= 2  # (one per shape of answer; executemany)
    ctx.commit()
    numbered = _statements(
        ctx, lambda: repo.mark_seqs([(i, n + 1, "x") for n, i in enumerate(ids)])
    )
    assert len(numbered) == 1


def test_own_changes_among_others_in_a_feed_converge(pair):
    """Own entries come back numbered among another device's, with a run of
    them each side: everything ends numbered and equal on both devices."""
    laptop, phone, record = pair
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    made = [
        laptop.record_svc.add(
            "study", "encounter", {"site": f"s{i}"}, with_labels=False
        ).id
        for i in range(6)
    ]
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    for n, rid in enumerate(made):
        ctx = laptop if n % 2 == 0 else phone
        ctx.record_svc.delete_many([str(rid)])
        ctx.commit()
        ctx.sync_svc.sync()  # (each device's feed now mixes own and other)
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    for ctx in (laptop, phone):
        ctx._session.expire_all()
        assert (
            not ctx._session.query(AuditLog)
            .filter(AuditLog.sync_state == "pending")
            .count()
        )
        deletes = ctx._session.query(AuditLog).filter(
            AuditLog.action == "delete", AuditLog.entity_type == "record"
        )
        assert deletes.count() == 6
        assert not deletes.filter(AuditLog.hub_seq.is_(None)).count()
    for rid in made:
        for ctx in (laptop, phone):
            with pytest.raises(NotFoundError):
                ctx.record_svc.get(str(rid))
