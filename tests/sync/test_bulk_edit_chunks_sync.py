"""A bulk edit is saved a chunk at a time, and a sync may run between two
chunks: every record's change is an action of its own, so nothing is split
and both halves arrive."""

from __future__ import annotations

from civex.services import record_service


def _depths(ctx, ids: list[str]) -> list[float]:
    return [ctx.record_svc.get(i).data["depth"] for i in ids]


def test_a_sync_between_two_chunks_splits_nothing(pair, authority, monkeypatch):
    laptop, phone, record = pair
    monkeypatch.setattr(record_service, "BULK_EDIT_PAGE", 2)
    ids = [str(record.id)] + [
        str(
            laptop.record_svc.add(
                "study", "encounter", {"site": f"s{i}", "depth": float(i)}
            ).id
        )
        for i in range(4)
    ]
    laptop.commit()
    laptop.sync_svc.sync()

    reports = []
    with laptop.chunked_writes() as turn:
        for _ in laptop.record_svc.bulk_edit_chunks({"depth": 99.0}, ids=ids):
            turn()
            reports.append(laptop.sync_svc.sync())  # a sync after every chunk
    phone.sync_svc.sync()

    assert len(reports) == 3  # five records, two a chunk
    assert _depths(authority, ids) == [99.0] * 5
    assert _depths(phone, ids) == [99.0] * 5
    assert laptop.sync_svc.conflicts() == []
    # Still one event on the device that made it, undone as one.
    events, _ = laptop.history_svc.events(
        where={"field": "how", "op": "eq", "value": "edit"}, limit=5
    )
    assert len(events) == 1
    assert laptop.history_svc.revert_batch(events[0].batch.id).applied == 5
