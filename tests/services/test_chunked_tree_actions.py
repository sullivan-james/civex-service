"""Delete, restore, purge and move a chunk of whole trees at a time (so a long
one can show how far it has got and be stopped): the entries it writes are the
ones a single request writes, a stop leaves whole trees, and the counts it
reports add up."""

from __future__ import annotations

import uuid

import pytest

from civex.db.models import AuditLog
from civex.services import progress as progress_module
from civex.services import record_service
from civex.services.progress import registry as progress_registry


@pytest.fixture()
def forest(ctx, make_schema, make_collection):
    """Two identical collections, each of three trees of five records (a site,
    its two trials, a sample under each), so a chunk of 7 holds two trees."""
    make_schema("site", fields=[("name", "string")])
    make_schema("trial", fields=[("subject", "string")], parent="site")
    make_schema("sample", fields=[("label", "string")], parent="trial")
    for name in ("a", "b", "c", "d"):
        make_collection(name)

    def build(collection: str) -> list[list[uuid.UUID]]:
        trees = []
        for s in range(3):
            site = ctx.record_svc.add(collection, "site", {"name": f"s{s}"})
            ids = [site.id]
            for t in range(2):
                trial = ctx.record_svc.add(
                    collection,
                    "trial",
                    {"subject": f"t{s}{t}"},
                    parent_record_id=str(site.id),
                )
                sample = ctx.record_svc.add(
                    collection,
                    "sample",
                    {"label": f"x{s}{t}"},
                    parent_record_id=str(trial.id),
                )
                ids += [trial.id, sample.id]
            trees.append(ids)
        ctx.commit()
        return trees

    return build


def _entries(ctx, trees: list[list[uuid.UUID]], action: str | None = None):
    """What was logged for these records, made comparable between two
    collections: ids become (tree, depth in the tree), so the order siblings
    happen to come out of the database in does not matter. Returns, per tree,
    its entries in the order written as (action, depth); whether each tree's
    entries are together (a tree is one action) and in one action; the batches
    and instants used."""
    where = {r: (t, d) for t, tree in enumerate(trees) for r, d in zip(tree, DEPTH)}
    rows = (
        ctx._session.query(AuditLog)
        .filter(AuditLog.entity_type == "record", AuditLog.entity_id.in_(list(where)))
        .filter(AuditLog.action != "create")
        .order_by(AuditLog.local_seq, AuditLog.timestamp)
        .all()
    )
    if action:
        rows = [r for r in rows if r.action == action]
    per_tree: dict[int, list[tuple[str, int]]] = {}
    ops: dict[int, set] = {}
    order: list[int] = []
    for r in rows:
        tree, depth = where[r.entity_id]
        per_tree.setdefault(tree, []).append((r.action, depth))
        ops.setdefault(tree, set()).add(r.op_id)
        if not order or order[-1] != tree:
            order.append(tree)
    together = len(order) == len(set(order)) and all(len(o) == 1 for o in ops.values())
    return (
        per_tree,
        together,
        {r.batch_id for r in rows},
        {r.timestamp for r in rows},
    )


# Depth of each record of a tree as `forest` builds it: a site, then its two
# trials, each with a sample.
DEPTH = [0, 1, 2, 1, 2]


def _drive(ctx, chunks, stop_after: int | None = None) -> int:
    """What a request does: commit after each chunk; stop after `stop_after`."""
    n = 0
    with ctx.chunked_writes() as turn:
        for _ in chunks:
            turn()
            n += 1
            if stop_after is not None and n >= stop_after:
                chunks.close()
                break
    ctx.commit()
    return n


def _state(ctx, tree: list[uuid.UUID]) -> set[bool]:
    """Whether each record of a tree is deleted: one value when the tree is whole."""
    states = ctx.record_svc.records_repo.deleted_at_of(tree)
    return {states[r] is not None for r in tree}


def _roots(trees):
    return [str(t[0]) for t in trees]


# -- delete -------------------------------------------------------------------


def test_a_chunked_delete_writes_what_one_request_writes(ctx, forest, monkeypatch):
    one, other = forest("a"), forest("b")
    assert ctx.record_svc.delete_many(_roots(one)) == 3
    ctx.commit()

    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 7)
    chunks = ctx.record_svc.delete_many_chunks(_roots(other))
    assert _drive(ctx, chunks) == 2  # two trees, then one

    mine, together_one, batches_one, stamps_one = _entries(ctx, one, "delete")
    theirs, together, batches, stamps_other = _entries(ctx, other, "delete")
    assert mine == theirs and sum(map(len, theirs.values())) == 15
    assert len(stamps_one) == len(stamps_other) == 1  # one instant
    assert len(batches_one) == len(batches) == 1  # one batch, however many chunks
    # A tree is one action, its entries together, parents before children.
    assert together_one and together
    assert all(d == sorted(d) for d in ([x[1] for x in v] for v in theirs.values()))
    assert [_state(ctx, t) for t in other] == [{True}] * 3


def test_a_stopped_delete_keeps_whole_trees_and_says_how_many(ctx, forest, monkeypatch):
    trees = forest("a")
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 7)
    chunks = ctx.record_svc.delete_many_chunks(_roots(trees))
    results = []

    def keep():
        for r in chunks:
            results.append(r)
            yield r

    assert _drive(ctx, keep(), stop_after=1) == 1
    assert results == [(2, 10)]  # two chosen records, ten written
    states = [_state(ctx, t) for t in trees]
    assert sorted(map(sorted, states)) == [[False], [True], [True]]

    # Sending it again finishes it: what is gone is left alone.
    done = list(ctx.record_svc.delete_many_chunks(_roots(trees)))
    ctx.commit()
    assert done == [(1, 5)]
    assert [_state(ctx, t) for t in trees] == [{True}] * 3


def test_a_delete_reports_records_of_records(ctx, forest, monkeypatch):
    trees = forest("a")
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 7)
    progress = progress_registry.start("count-delete-1")
    seen: list[tuple[str, int, int]] = []
    advance = progress_module.Progress.advance

    def watch(self, done, total=None):
        advance(self, done, total)
        state = progress_registry.get("count-delete-1")
        seen.append((state["phase"], state["done"], state["total"]))

    monkeypatch.setattr(progress_module.Progress, "advance", watch)
    _drive(ctx, ctx.record_svc.delete_many_chunks(_roots(trees), progress=progress))
    # After each statement (7 records, the rest of the chunk, the last tree).
    assert seen == [("Deleting records", n, 15) for n in (7, 10, 15)]


def test_one_tree_bigger_than_a_chunk_is_committed_whole(ctx, forest, monkeypatch):
    trees = forest("a")
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 2)
    seen = []
    chunks = ctx.record_svc.delete_chunks(str(trees[0][0]))
    for result in chunks:
        seen.append(result)
        # Never between a parent and what sits under it.
        assert _state(ctx, trees[0]) == {True}
    assert seen == [(1, 5)]


def test_forced_references_are_cleared_only_for_what_was_deleted(
    ctx, make_schema, make_collection, monkeypatch
):
    make_schema("thing", fields=[("name", "string")])
    ctx.schema_svc.add_field("thing", "link", "reference")
    make_collection("c")
    ctx.commit()
    targets = [ctx.record_svc.add("c", "thing", {"name": f"t{i}"}) for i in range(3)]
    holder = ctx.record_svc.add("c", "thing", {"name": "h", "link": str(targets[2].id)})
    ctx.commit()
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 1)
    ids = [str(t.id) for t in targets[:2]]
    # Not pointed at: it goes.  The one the holder points at is refused whole.
    with pytest.raises(Exception, match="referenced"):
        _drive(ctx, ctx.record_svc.delete_many_chunks([*ids, str(targets[2].id)]))
    ctx.rollback()
    assert _state(ctx, [t.id for t in targets]) == {False}
    # Forced: cleared with the record it pointed at, in its own chunk.
    _drive(
        ctx,
        ctx.record_svc.delete_many_chunks([*ids, str(targets[2].id)], force=True),
    )
    assert ctx.record_svc.get(str(holder.id)).data.get("link") is None
    assert _state(ctx, [t.id for t in targets]) == {True}


# -- restore ------------------------------------------------------------------


def test_a_chunked_restore_writes_what_one_request_writes(ctx, forest, monkeypatch):
    one, other = forest("a"), forest("b")
    ctx.record_svc.delete_many(_roots(one) + _roots(other))
    ctx.commit()
    ids_one = [str(r) for t in one for r in t]
    ids_other = [str(r) for t in other for r in t]

    result = ctx.record_svc.restore_records(ids_one)
    ctx.commit()
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 7)
    chunks = ctx.record_svc.restore_records_chunks(ids_other)
    assert _drive(ctx, chunks) == 2

    mine, together_one, batches_one, _ = _entries(ctx, one, "restore")
    theirs, together, batches, _ = _entries(ctx, other, "restore")
    assert mine == theirs and sum(map(len, theirs.values())) == 15
    assert together_one and together
    assert len(batches_one) == len(batches) == 1
    last = None
    for last in ctx.record_svc.restore_records_chunks(ids_other):
        pass
    assert (result.restored, result.came_back) == (15, 15)
    assert last is not None and (last.restored, last.came_back) == (0, 0)
    assert [_state(ctx, t) for t in other] == [{False}] * 3


def test_a_stopped_restore_brings_back_whole_trees(ctx, forest, monkeypatch):
    trees = forest("a")
    ctx.record_svc.delete_many(_roots(trees))
    ctx.commit()
    ids = [str(r) for t in trees for r in t]
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 7)
    assert _drive(ctx, ctx.record_svc.restore_records_chunks(ids), stop_after=1) == 1
    states = [_state(ctx, t) for t in trees]  # whole trees, two of three
    assert sorted(map(sorted, states)) == [[False], [False], [True]]


def test_restoring_one_record_with_a_big_subtree_reports_progress(
    ctx, forest, monkeypatch
):
    trees = forest("a")
    ctx.record_svc.delete(str(trees[0][0]))
    ctx.commit()
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 2)
    progress = progress_registry.start("restore-one-1")
    steps = list(ctx.record_svc.restore_chunks(str(trees[0][0]), progress=progress))
    ctx.commit()
    state = progress_registry.get("restore-one-1")
    assert steps == [5]  # one tree, one commit
    assert (state["phase"], state["done"], state["total"]) == (
        "Restoring records",
        5,
        5,
    )


# -- purge --------------------------------------------------------------------


def test_a_chunked_purge_removes_the_same_records_and_leaves_the_same_stones(
    ctx, forest, monkeypatch
):
    one, other = forest("a"), forest("b")
    ctx.record_svc.delete_many([str(one[0][0]), str(other[0][0])])
    ctx.commit()

    ctx.record_svc.purge(str(one[0][0]))
    ctx.commit()
    monkeypatch.setattr(record_service, "_PURGE_CHUNK", 2)
    assert _drive(ctx, ctx.record_svc.purge_chunks(str(other[0][0]))) == 3

    def stones(trees):
        per_tree, *_ = _entries(ctx, trees, "purge")
        return {t: sorted(v) for t, v in per_tree.items()}

    # One stone for each of the five records of the tree, whatever the order.
    assert stones(one) == stones(other) == {0: sorted(("purge", d) for d in DEPTH)}
    for tree in (one[0], other[0]):
        assert ctx.record_svc.records_repo.deleted_at_of(tree) == {}


def test_a_stopped_purge_leaves_a_whole_deleted_tree_above_what_went(
    ctx, forest, monkeypatch
):
    trees = forest("a")
    ctx.record_svc.delete(str(trees[0][0]))
    ctx.commit()
    monkeypatch.setattr(record_service, "_PURGE_CHUNK", 2)
    progress = progress_registry.start("purge-stop-1")
    assert (
        _drive(
            ctx,
            ctx.record_svc.purge_chunks(str(trees[0][0]), progress=progress),
            stop_after=1,
        )
        == 1
    )
    left = ctx.record_svc.records_repo.deleted_at_of(trees[0])
    assert len(left) == 3 and trees[0][0] in left  # the top stays, deleted
    # What stays still hangs together: every record left has its parent.
    for rid in left:
        record = ctx.record_svc.records_repo.get_by_prefix(
            str(rid), include_deleted=True
        )
        assert record.parent_record_id is None or record.parent_record_id in left
    assert progress_registry.get("purge-stop-1")["done"] == 2
    # Purging again takes the rest.
    _drive(ctx, ctx.record_svc.purge_chunks(str(trees[0][0])))
    assert ctx.record_svc.records_repo.deleted_at_of(trees[0]) == {}


# -- move ---------------------------------------------------------------------


def test_a_chunked_move_writes_what_one_request_writes(ctx, forest, monkeypatch):
    one, other = forest("a"), forest("b")
    ctx.record_svc.move("c", ids=_roots(one))
    ctx.commit()
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 7)
    chunks = ctx.record_svc.move_chunks("d", ids=_roots(other))
    assert _drive(ctx, chunks) == 2

    mine, together_one, batches_one, stamps_one = _entries(ctx, one, "update")
    theirs, together, batches, stamps_other = _entries(ctx, other, "update")
    assert mine == theirs and sum(map(len, theirs.values())) == 15
    assert together_one and together and len(batches_one) == len(batches) == 1
    assert len(stamps_one) == len(stamps_other) == 1
    for tree in other:
        for rid in tree:
            assert ctx.record_svc.get(str(rid)).dataset_name == "d"


def test_a_stopped_move_keeps_the_trees_it_moved_whole(ctx, forest, monkeypatch):
    trees = forest("a")
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 7)
    results = []

    def keep():
        for r in ctx.record_svc.move_chunks("c", ids=_roots(trees)):
            results.append(r)
            yield r

    chunks = keep()
    assert _drive(ctx, chunks, stop_after=1) == 1
    assert [(r.roots, r.records) for r in results] == [(2, 10)]
    where = [
        {ctx.record_svc.get(str(rid)).dataset_name for rid in tree} for tree in trees
    ]
    # No tree split across collections; two of the three moved.
    assert sorted(map(sorted, where)) == [["a"], ["c"], ["c"]]


# -- other saves go in between two chunks --------------------------------------


def _live_top(ctx, trees):
    """A tree not touched yet (its chunk is still to come)."""
    return next(t for t in trees if _state(ctx, t) == {False})


def test_a_record_added_under_a_later_tree_between_chunks_goes_with_it(
    ctx, forest, monkeypatch
):
    trees = forest("a")
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 7)
    chunks = ctx.record_svc.delete_many_chunks(_roots(trees))
    with ctx.chunked_writes() as turn:
        next(chunks)
        turn()
        later = _live_top(ctx, trees)
        newcomer = ctx.record_svc.add(
            "a", "trial", {"subject": "late"}, parent_record_id=str(later[0])
        )
        ctx.commit()
        for _ in chunks:
            turn()
    ctx.commit()
    # Never left live under a deleted parent.
    assert _state(ctx, [*later, newcomer.id]) == {True}


def test_a_reference_added_between_chunks_stops_the_rest_and_keeps_the_first(
    ctx, forest, make_schema, monkeypatch
):
    trees = forest("a")
    ctx.schema_svc.add_field("site", "link", "reference")
    ctx.commit()
    outsider = ctx.record_svc.add("a", "site", {"name": "out"})
    ctx.commit()
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 7)
    chunks = ctx.record_svc.delete_many_chunks(_roots(trees))
    with ctx.chunked_writes() as turn:
        next(chunks)
        turn()
        later = _live_top(ctx, trees)
        ctx.record_svc.update(str(outsider.id), {"link": str(later[0])})
        ctx.commit()
        with pytest.raises(Exception, match="referenc"):
            next(chunks)
    ctx.rollback()
    assert sorted(map(sorted, [_state(ctx, t) for t in trees])) == [
        [False],
        [True],
        [True],
    ]


def test_forced_clearing_saves_a_record_that_points_at_several_once(
    ctx, make_schema, make_collection, monkeypatch
):
    make_schema("thing", fields=[("name", "string")])
    ctx.schema_svc.add_field("thing", "links", "reference_list")
    make_collection("c")
    ctx.commit()
    targets = [ctx.record_svc.add("c", "thing", {"name": f"t{i}"}) for i in range(3)]
    holder = ctx.record_svc.add(
        "c", "thing", {"name": "h", "links": [str(t.id) for t in targets]}
    )
    ctx.commit()
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 1)
    _drive(
        ctx,
        ctx.record_svc.delete_many_chunks([str(t.id) for t in targets], force=True),
    )
    updates = (
        ctx._session.query(AuditLog)
        .filter(AuditLog.entity_id == holder.id, AuditLog.action == "update")
        .count()
    )
    assert updates == 1
    assert not ctx.record_svc.get(str(holder.id)).data.get("links")


def test_a_purge_stops_when_a_record_is_restored_between_chunks(
    ctx, forest, monkeypatch
):
    trees = forest("a")
    ctx.record_svc.delete(str(trees[0][0]))
    ctx.commit()
    monkeypatch.setattr(record_service, "_PURGE_CHUNK", 2)
    chunks = ctx.record_svc.purge_chunks(str(trees[0][0]))
    with ctx.chunked_writes() as turn:
        assert next(chunks) == 2
        turn()
        ctx.record_svc.restore(str(trees[0][0]))  # the root, with what is left
        ctx.commit()
        assert list(chunks) == []  # stopped: nothing live is removed
    ctx.commit()
    left = ctx.record_svc.records_repo.deleted_at_of(trees[0])
    assert len(left) == 3 and set(left.values()) == {None}
    # Their history is whole: only the two removed were tombstoned.
    purged = ctx._session.query(AuditLog).filter(AuditLog.action == "purge").count()
    assert purged == 2
    assert (
        ctx._session.query(AuditLog)
        .filter(AuditLog.entity_id.in_(list(left)), AuditLog.action == "delete")
        .count()
        == 3
    )


def test_a_move_takes_a_record_added_meanwhile_and_stops_if_the_target_went(
    ctx, forest, monkeypatch
):
    trees = forest("a")
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 7)
    chunks = ctx.record_svc.move_chunks("c", ids=_roots(trees))
    with ctx.chunked_writes() as turn:
        next(chunks)
        turn()
        later = _live_top(ctx, trees)  # unchanged: not in "c" yet
        later = next(
            t for t in trees if ctx.record_svc.get(str(t[0])).dataset_name == "a"
        )
        newcomer = ctx.record_svc.add(
            "a", "trial", {"subject": "late"}, parent_record_id=str(later[0])
        )
        ctx.commit()
        for _ in chunks:  # no key error: the new record moves with its parent
            turn()
    ctx.commit()
    assert ctx.record_svc.get(str(newcomer.id)).dataset_name == "c"

    more = forest("b")
    chunks = ctx.record_svc.move_chunks("d", ids=_roots(more))
    with ctx.chunked_writes() as turn:
        next(chunks)
        turn()
        ctx.dataset_svc.delete("d")
        ctx.commit()
        with pytest.raises(Exception, match="changed while"):
            next(chunks)
    ctx.rollback()
    moved = [
        {
            ctx.record_svc.records_repo.get_by_prefix(
                str(r), include_deleted=True
            ).dataset_id
            for r in t
        }
        for t in more
    ]
    assert all(len(m) == 1 for m in moved)  # still whole trees
