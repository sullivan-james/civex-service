"""A bulk operation is one event in history, not one row per record."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from civex.context import AppContext


@pytest.fixture()
def tree(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("rate", "integer")], parent="encounter")
    make_collection("humpback")
    enc = make_record("humpback", "encounter", {"site": "Stellwagen"})
    for rate in (96, 48):
        make_record(
            "humpback", "recording", {"rate": rate}, parent_record_id=str(enc.id)
        )
    return enc


def leaf(field: str, value, op: str = "eq") -> dict:
    return {"field": field, "op": op, "value": value}


def _events(ctx: AppContext, *conditions: dict, **kw):
    where = {"and": list(conditions)} if conditions else None
    return ctx.history_svc.events(where=where, limit=100, **kw)


def _batches(ctx: AppContext) -> int:
    from civex.db.models import AuditBatch

    return ctx._session.query(AuditBatch).count()


def test_deleting_a_tree_is_one_event_that_says_what_it_held(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()

    events, _ = _events(ctx, leaf("change", "delete"))
    assert len(events) == 1
    event = events[0]
    assert event.batch is not None and event.batch.kind == "delete"
    assert event.count == 3
    assert event.parts == [{"entity_type": "record", "action": "delete", "count": 3}]


def test_deleting_one_record_stays_a_single_entry(ctx: AppContext, tree):
    one = ctx.record_svc.find("humpback", "recording")[0]
    ctx.record_svc.delete(str(one.id))
    ctx.commit()
    events, _ = _events(ctx, leaf("change", "delete"))
    assert len(events) == 1
    assert events[0].batch is None and events[0].entry is not None
    assert events[0].entry.changes  # a single change carries its field changes


def test_restoring_a_tree_is_one_event(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree.id))
    ctx.record_svc.restore(str(tree.id))
    ctx.commit()
    events, _ = _events(ctx, leaf("change", "restore"))
    assert [(e.batch.kind, e.count) for e in events] == [("restore", 3)]


def test_a_workflow_run_is_one_event_with_its_label_and_what_started_it(
    ctx: AppContext, tree, make_record
):
    with ctx.history_svc.batch("workflow", "tag-recordings", "job-1"):
        for i in range(4):
            make_record("humpback", "encounter", {"site": f"s{i}"})
        # A delete inside the run joins the run's batch rather than its own.
        ctx.record_svc.delete(str(tree.id))
    ctx.commit()

    events, total = _events(ctx, leaf("how", "workflow"))
    assert total == 1
    run = events[0]
    assert (run.batch.label, run.batch.ref) == ("tag-recordings", "job-1")
    assert run.count == 4 + 3
    assert {(p["action"], p["count"]) for p in run.parts} == {
        ("create", 4),
        ("delete", 3),
    }
    assert _batches(ctx) == 1


def test_a_batch_that_writes_nothing_leaves_no_trace(ctx: AppContext, tree):
    before = _batches(ctx)
    with ctx.history_svc.batch("workflow", "noop"):
        pass
    ctx.commit()
    assert _batches(ctx) == before


def test_a_batches_entries_are_paged_separately(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()
    event = _events(ctx, leaf("change", "delete"))[0][0]
    assert event.batch is not None
    summary = ctx.history_svc.batch_event(event.batch.id)
    assert summary.count == 3
    members = ctx.history_svc.page(batch_id=event.batch.id, limit=2)
    assert len(members) == 2 and all(m.changes for m in members)
    assert ctx.history_svc.count(batch_id=event.batch.id) == 3


def test_events_filter_by_kind_of_event(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()
    assert _events(ctx, leaf("how", "delete"))[1] == 1
    assert _events(ctx, leaf("how", "workflow"))[1] == 0
    bulk, single = (
        _events(ctx, leaf("how", "single", "ne"))[1],
        _events(ctx, leaf("how", "single"))[1],
    )
    assert bulk == 1
    assert single >= 3  # the setup creates, none of them in a batch


def test_filters_count_only_the_matching_changes_in_a_batch(
    ctx: AppContext, tree, make_record
):
    with ctx.history_svc.batch("import", "p.csv"):
        make_record("humpback", "encounter", {"site": "a"})
        make_record("humpback", "encounter", {"site": "b"})
    ctx.commit()
    event = _events(ctx, leaf("how", "import"))[0][0]
    assert event.count == 2
    assert _events(ctx, leaf("how", "import"), leaf("change", "update"))[1] == 0
    assert _events(ctx, leaf("how", "import"), leaf("kind", "record"))[0][0].count == 2


def test_search_finds_values_and_batch_labels(ctx: AppContext, tree, make_record):
    with ctx.history_svc.batch("import", "humpback-2024.csv"):
        make_record("humpback", "encounter", {"site": "Georges"})
    ctx.commit()
    assert _events(ctx, search="stellwagen")[1] >= 1  # a stored value
    by_label = _events(ctx, search="2024.csv")[0]
    assert [e.batch.kind for e in by_label] == ["import"]
    assert _events(ctx, search="no-such-thing")[1] == 0


def test_since_and_order(ctx: AppContext, tree):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert _events(ctx, leaf("when", future, "gte"))[1] == 0
    newest, _ = _events(ctx)
    oldest, _ = _events(ctx, newest_first=False)
    assert newest[0].timestamp >= newest[-1].timestamp
    assert oldest[0].timestamp <= oldest[-1].timestamp


def test_paging_events_counts_events_not_entries(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree.id))  # 3 entries, one event
    ctx.commit()
    all_events, total = _events(ctx)
    page, total_again = ctx.history_svc.events(limit=1, offset=0)
    assert total == total_again == len(all_events)
    assert len(page) == 1


# --- undoing a bulk delete as the one event it was ---------------------------


def _delete_batch_id(ctx: AppContext):
    events, _ = _events(ctx, leaf("change", "delete"))
    return events[0].batch.id


def test_a_whole_delete_can_be_restored_from_its_one_event(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()
    batch_id = _delete_batch_id(ctx)

    plan = ctx.history_svc.plan_restore_all(batch_id=batch_id)
    # The parent and both children were deleted; they come back together.
    assert plan.records == 3 and plan.restores == 3 and plan.blocked == 0

    result = ctx.history_svc.restore_all(batch_id=batch_id)
    ctx.commit()
    assert result.records == 3 and result.blocked == 0
    assert ctx.record_svc.get(str(tree.id)).deleted_at is None
    assert len(ctx.record_svc.find("humpback", "recording")) == 2


def test_restoring_one_event_leaves_other_deletes_alone(ctx: AppContext, tree):
    one = ctx.record_svc.find("humpback", "recording")[0]
    ctx.record_svc.delete(str(one.id))  # a separate, earlier delete
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()
    batch_id = _delete_batch_id(ctx)

    ctx.history_svc.restore_all(batch_id=batch_id)
    ctx.commit()

    assert ctx.record_svc.get(str(tree.id)).deleted_at is None
    # The recording deleted on its own earlier stays deleted.
    assert [r.id for r in ctx.record_svc.find("humpback", "recording")] != []
    assert str(one.id) not in {
        str(r.id) for r in ctx.record_svc.find("humpback", "recording")
    }


def test_a_batch_that_is_not_an_id_is_refused(ctx: AppContext, tree):
    from civex.domain.exceptions import ValidationError

    with pytest.raises(ValidationError):
        ctx.history_svc.plan_restore_all(batch_id="not-an-id")


def _queries(ctx: AppContext, fn) -> int:
    from sqlalchemy import event

    count = {"n": 0}
    engine = ctx._session.get_bind()

    def bump(*_args, **_kwargs):
        count["n"] += 1

    event.listen(engine, "before_cursor_execute", bump)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", bump)
    return count["n"]


def test_describing_and_undoing_a_bulk_delete_costs_the_same_however_big_it_is(
    ctx: AppContext, make_schema, make_collection, make_record
):
    """Restoring a recording with 70 selections used to take a dozen queries
    per record to even describe (and the dialog sat on a spinner). The cost is
    now a few queries, whatever the size of the delete."""
    make_schema("recording", fields=[("site", "string")])
    make_schema("selection", fields=[("n", "integer")], parent="recording")
    make_collection("c")

    def delete_tree(children: int):
        rec = make_record("c", "recording", {"site": "x"})
        for i in range(children):
            make_record("c", "selection", {"n": i}, parent_record_id=str(rec.id))
        ctx.record_svc.delete(str(rec.id))
        ctx.commit()
        events, _ = _events(ctx, leaf("change", "delete"))
        return events[0].batch.id

    small = delete_tree(3)
    small_plan = _queries(ctx, lambda: ctx.history_svc.plan_restore_all(batch_id=small))
    small_restore = _queries(ctx, lambda: ctx.history_svc.restore_all(batch_id=small))
    ctx.commit()

    big = delete_tree(60)
    big_plan = _queries(ctx, lambda: ctx.history_svc.plan_restore_all(batch_id=big))
    big_restore = _queries(ctx, lambda: ctx.history_svc.restore_all(batch_id=big))
    ctx.commit()

    assert big_plan == small_plan <= 12
    assert big_restore == small_restore <= 20
    assert len(ctx.record_svc.find("c", "selection", limit=500)) == 63


def test_a_record_under_a_deleted_schema_waits_unless_the_schema_comes_too(
    ctx: AppContext, tree
):
    ctx.schema_svc.delete("recording")
    ctx.commit()
    # Everything deleted: the schema and its records come back together.
    plan = ctx.history_svc.plan_restore_all()
    assert plan.schemas == 1 and plan.blocked == 0
    ctx.history_svc.restore_all()
    ctx.commit()
    assert len(ctx.record_svc.find("humpback", "recording")) == 2


def test_a_child_deleted_earlier_comes_back_in_a_second_round(ctx: AppContext, tree):
    """A child deleted on its own, then its parent: restoring both takes two
    rounds (the child is held back until the parent is live), and it works."""
    child = ctx.record_svc.find("humpback", "recording")[0]
    ctx.record_svc.delete(str(child.id))
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()

    plan = ctx.history_svc.plan_restore_all()
    assert plan.blocked == 0  # the parent is in the set, so the child is covered
    result = ctx.history_svc.restore_all()
    ctx.commit()
    assert result.blocked == 0
    assert ctx.record_svc.get(str(tree.id)).deleted_at is None
    assert ctx.record_svc.get(str(child.id)).deleted_at is None


# --- restoring one child of a deleted parent ---------------------------------


def test_each_deleted_record_has_its_own_entry_even_though_they_show_as_one(
    ctx: AppContext, tree
):
    from civex.db.models import AuditLog

    ctx.record_svc.delete(str(tree.id))
    ctx.commit()
    entries = (
        ctx._session.query(AuditLog)
        .filter(AuditLog.action == "delete", AuditLog.entity_type == "record")
        .all()
    )
    assert len(entries) == 3  # the encounter and its two recordings
    assert len({e.batch_id for e in entries}) == 1  # tied together, not merged


def test_restoring_one_child_can_leave_its_siblings_deleted(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()
    deleted_children = [
        e.entity_id
        for e in ctx.history_svc.page(limit=50)
        if e.action == "delete" and e.entity_id != tree.id
    ]
    one, other = deleted_children[0], deleted_children[1]

    plan = ctx.record_svc.restore_plan(str(one))
    assert plan.blocked_by is not None and plan.blocked_by.kind == "record"
    assert plan.records == 1
    # One deleted parent would have to come back with it.
    assert plan.parents_needed == 1
    # Without asking for it, a child still waits for its parent.
    from civex.domain.exceptions import ValidationError

    with pytest.raises(ValidationError):
        ctx.record_svc.restore(str(one))

    ctx.record_svc.restore(str(one), with_parents=True)
    ctx.commit()

    assert ctx.record_svc.get(str(tree.id)).deleted_at is None
    assert ctx.record_svc.get(str(one)).deleted_at is None
    assert ctx.record_svc.labels([str(other)])[0].deleted_at is not None
    assert [str(r.id) for r in ctx.record_svc.find("humpback", "recording")] == [
        str(one)
    ]


def test_restoring_the_parent_still_brings_everything_back(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()
    plan = ctx.record_svc.restore_plan(str(tree.id))
    assert plan.records == 3 and plan.parents_needed is None
    ctx.record_svc.restore(str(tree.id))
    ctx.commit()
    assert len(ctx.record_svc.find("humpback", "recording")) == 2


def test_a_record_can_come_back_without_what_was_deleted_with_it(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()

    ctx.record_svc.restore(str(tree.id), only_this=True)
    ctx.commit()

    assert ctx.record_svc.get(str(tree.id)).deleted_at is None
    # Its two recordings were deleted with it and stay deleted.
    assert ctx.record_svc.find("humpback", "recording") == []


def test_exactly_the_chosen_records_come_back_with_the_parents_they_need(
    ctx: AppContext, tree
):
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()
    children = [
        e.entity_id
        for e in ctx.history_svc.page(limit=50)
        if e.action == "delete" and e.entity_id != tree.id
    ]

    result = ctx.record_svc.restore_records([str(children[0])])
    ctx.commit()

    assert result.restored == 1 and result.came_back == 2 and result.left == []
    assert ctx.record_svc.get(str(tree.id)).deleted_at is None
    assert [str(r.id) for r in ctx.record_svc.find("humpback", "recording")] == [
        str(children[0])
    ]


def test_chosen_records_under_a_deleted_parent_are_left_when_parents_are_not_wanted(
    ctx: AppContext, tree
):
    ctx.record_svc.delete(str(tree.id))
    ctx.commit()
    child = next(
        e.entity_id
        for e in ctx.history_svc.page(limit=50)
        if e.action == "delete" and e.entity_id != tree.id
    )

    result = ctx.record_svc.restore_records([str(child)], with_parents=False)
    ctx.commit()

    assert result.restored == 0 and result.left == [str(child)]
    assert ctx.record_svc.find("humpback", "recording") == []


def test_restoring_chosen_records_leaves_alone_one_held_by_a_deleted_schema(
    ctx: AppContext, tree
):
    ctx.record_svc.delete(str(tree.id))
    ctx.schema_svc.delete("encounter")
    ctx.commit()

    result = ctx.record_svc.restore_records([str(tree.id)])
    assert result.restored == 0 and result.left == [str(tree.id)]
