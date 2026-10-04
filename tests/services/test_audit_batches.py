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
