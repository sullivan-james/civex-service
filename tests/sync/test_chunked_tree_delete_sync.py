"""A delete or a restore is committed a chunk of whole trees at a time, and a
sync may run between two chunks: what the authority and the other device see
is always whole trees, and when it is done they agree with the device."""

from __future__ import annotations

import uuid

from civex.services import record_service


def _trees(laptop) -> list[list[uuid.UUID]]:
    laptop.schema_svc.create("note", parent="encounter")
    laptop.schema_svc.add_field("note", "text", "string")
    laptop.commit()
    laptop.sync_svc.sync()
    trees = []
    for i in range(3):
        top = laptop.record_svc.add(
            "study", "encounter", {"site": f"s{i}", "depth": 1.0}
        )
        note = laptop.record_svc.add(
            "study", "note", {"text": f"n{i}"}, parent_record_id=str(top.id)
        )
        trees.append([top.id, note.id])
    laptop.commit()
    laptop.sync_svc.sync()
    return trees


def _whole(ctx, trees) -> list[set[bool]]:
    states = ctx.record_svc.records_repo.deleted_at_of([r for t in trees for r in t])
    return [{states.get(r) is not None for r in t if r in states} for t in trees]


def test_a_sync_between_two_chunks_of_a_delete_and_of_a_restore_splits_no_tree(
    pair, authority, monkeypatch
):
    laptop, phone, _ = pair
    trees = _trees(laptop)
    phone.sync_svc.sync()
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 2)
    roots = [str(t[0]) for t in trees]

    seen = []
    with laptop.chunked_writes() as turn:
        for _chunk in laptop.record_svc.delete_many_chunks(roots):
            turn()
            laptop.sync_svc.sync()
            seen.append(_whole(authority, trees))
    phone.sync_svc.sync()

    assert len(seen) == 3
    assert all(len(s) <= 1 for state in seen for s in state)  # no tree half way
    assert seen[0][0] == {True}
    assert _whole(authority, trees) == [{True}] * 3
    assert _whole(phone, trees) == [{True}] * 3
    assert laptop.sync_svc.conflicts() == []

    with laptop.chunked_writes() as turn:
        for _chunk in laptop.record_svc.restore_records_chunks(
            [str(r) for t in trees for r in t]
        ):
            turn()
            laptop.sync_svc.sync()
            assert all(len(s) <= 1 for s in _whole(authority, trees))
    phone.sync_svc.sync()
    assert _whole(authority, trees) == [{False}] * 3
    assert _whole(phone, trees) == [{False}] * 3


def test_a_sync_between_chunks_of_a_move_and_a_purge_splits_no_tree(
    pair, authority, monkeypatch
):
    laptop, phone, _ = pair
    laptop.dataset_svc.create("elsewhere")
    laptop.commit()
    trees = _trees(laptop)
    phone.sync_svc.sync()
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 2)
    roots = [str(t[0]) for t in trees]

    def where(ctx, tree):
        return {
            ctx.record_svc.records_repo.get_by_prefix(
                str(r), include_deleted=True
            ).dataset_id
            for r in tree
        }

    with laptop.chunked_writes() as turn:
        for _chunk in laptop.record_svc.move_chunks("elsewhere", ids=roots):
            turn()
            laptop.sync_svc.sync()
            assert all(len(where(authority, t)) == 1 for t in trees)
    phone.sync_svc.sync()
    assert all(len(where(phone, t)) == 1 for t in trees)
    assert where(phone, trees[0]) == where(laptop, trees[0])

    laptop.record_svc.delete_many(roots)
    laptop.commit()
    laptop.sync_svc.sync()
    monkeypatch.setattr(record_service, "_PURGE_CHUNK", 1)
    with laptop.chunked_writes() as turn:
        for _chunk in laptop.record_svc.purge_chunks(roots[0]):
            turn()
            laptop.sync_svc.sync()
    phone.sync_svc.sync()
    for ctx in (laptop, authority, phone):
        assert ctx.record_svc.records_repo.deleted_at_of(trees[0]) == {}
        assert len(ctx.record_svc.records_repo.deleted_at_of(trees[1])) == 2
    assert laptop.sync_svc.conflicts() == []
