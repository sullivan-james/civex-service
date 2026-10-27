"""Moving records to another collection (or inside another record): the tree
goes whole and keeps its ids, history says what happened as one event, and
anything a move would break refuses it beforehand."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import NotAllowedError, ValidationError
from civex.domain.permissions import Permissions
from civex.domain.query import RecordQuery


def _tree(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("site", fields=[("name", "string")])
    make_schema("visit", fields=[("when", "string")], parent="site")
    make_schema("sample", fields=[("code", "string")], parent="visit")
    make_collection("survey")
    make_collection("archive")
    site = make_record("survey", "site", {"name": "a"})
    visit = make_record(
        "survey", "visit", {"when": "may"}, parent_record_id=str(site.id)
    )
    sample = make_record(
        "survey", "sample", {"code": "s1"}, parent_record_id=str(visit.id)
    )
    return site, visit, sample


def _in(ctx: AppContext, record_id, collection: str) -> bool:
    record = ctx.record_svc.get(str(record_id))
    return record.dataset_id == ctx.dataset_svc.get(collection).id


def test_a_record_moves_with_everything_beneath_it_and_keeps_its_ids(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, visit, sample = _tree(ctx, make_schema, make_collection, make_record)
    ctx.record_svc.delete(str(sample.id))  # a deleted child goes too
    ctx.commit()

    plan = ctx.record_svc.plan_move("archive", ids=[str(site.id)])
    assert (plan.roots, plan.records, plan.skipped, plan.sources) == (
        1,
        3,
        0,
        ["survey"],
    )
    assert plan.can_move

    result = ctx.record_svc.move("archive", ids=[str(site.id)])
    ctx.commit()

    assert (result.roots, result.records) == (1, 3)
    for record in (site, visit):
        assert _in(ctx, record.id, "archive")
        assert ctx.record_svc.get(str(record.id)).data  # values kept
    deleted = ctx.record_svc.labels([str(sample.id)])[0]
    assert deleted.deleted_at is not None
    assert deleted.dataset_id == ctx.dataset_svc.get("archive").id
    assert ctx.dataset_svc.get("survey").record_count == 0
    assert ctx.record_svc.get(str(visit.id)).parent_record_id == site.id


def test_a_move_is_one_event_of_edits_in_history(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, visit, sample = _tree(ctx, make_schema, make_collection, make_record)
    ctx.record_svc.move("archive", ids=[str(site.id)])
    ctx.commit()

    event = ctx.history_svc.events(limit=5)[0][0]
    assert event.batch is not None and event.batch.kind == "move"
    entries = ctx.history_svc.page(batch_id=event.batch.id, limit=10)
    assert {e.action for e in entries} == {"update"}
    assert {str(e.entity_id) for e in entries} == {
        str(site.id),
        str(visit.id),
        str(sample.id),
    }
    changed = {c["field"] for e in entries for c in e.changes}
    assert "dataset_id" in changed
    # One action for the tree: the move goes in whole, or not at all.
    sent = [e for e in ctx.sync_repo.pending_entries(50) if e.entity_type == "record"]
    assert len({e.op for e in sent if e.action == "update"}) == 1


def test_moving_inside_another_record_re_parents(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, visit, sample = _tree(ctx, make_schema, make_collection, make_record)
    other = make_record("survey", "site", {"name": "b"})

    ctx.record_svc.move("survey", str(other.id), ids=[str(visit.id)])
    ctx.commit()

    moved = ctx.record_svc.get(str(visit.id))
    assert moved.parent_record_id == other.id
    assert ctx.record_svc.get(str(sample.id)).parent_record_id == visit.id
    assert ctx.record_svc._records.list_children_of([site.id]) == []


def test_a_record_already_where_it_would_go_is_skipped(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, _, _ = _tree(ctx, make_schema, make_collection, make_record)
    plan = ctx.record_svc.plan_move("survey", ids=[str(site.id)])
    assert (plan.roots, plan.records, plan.skipped) == (0, 0, 1)
    assert not plan.can_move
    assert ctx.record_svc.move("survey", ids=[str(site.id)]).records == 0


def test_a_kind_can_only_sit_where_it_nests(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, visit, _ = _tree(ctx, make_schema, make_collection, make_record)
    plan = ctx.record_svc.plan_move("archive", ids=[str(visit.id)])
    assert plan.problems == ["A Visit sits inside a Site: choose the Site it goes in."]
    with pytest.raises(ValidationError, match="choose the Site"):
        ctx.record_svc.move("archive", ids=[str(visit.id)])

    other = make_record("archive", "site", {"name": "b"})
    plan = ctx.record_svc.plan_move("archive", str(other.id), ids=[str(site.id)])
    assert plan.problems == [
        "A Site can't go inside 'b' (site): it sits at the top of a collection."
    ]


def test_a_record_cannot_move_inside_itself(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, visit, _ = _tree(ctx, make_schema, make_collection, make_record)
    plan = ctx.record_svc.plan_move("survey", str(visit.id), ids=[str(site.id)])
    assert "inside itself" in " ".join(plan.problems)


def test_a_parent_must_be_in_the_target_collection(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, visit, _ = _tree(ctx, make_schema, make_collection, make_record)
    with pytest.raises(ValidationError, match="is not in collection 'archive'"):
        ctx.record_svc.plan_move("archive", str(site.id), ids=[str(visit.id)])


def test_a_reference_that_would_break_refuses_the_move(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("tag", fields=[("name", "string")])
    make_schema("note", fields=[("tag", "reference"), ("text", "string")])
    make_collection("survey")
    make_collection("archive")
    tag = make_record("survey", "tag", {"name": "red"})
    note = make_record("survey", "note", {"tag": str(tag.id), "text": "x"})

    # The note would reference a record left behind in a local collection.
    plan = ctx.record_svc.plan_move("archive", ids=[str(note.id)])
    assert plan.problems == [
        "1 record being moved references records that would stay behind in "
        "'survey', which only its own records can reference. Move those too, "
        "or make 'survey' global."
    ]
    # The tag would be referenced from a collection that can't reach it.
    plan = ctx.record_svc.plan_move("archive", ids=[str(tag.id)])
    assert plan.problems == [
        "1 record in 'survey' references records being moved and could no "
        "longer reach them in 'archive'. Move those too, or make 'archive' "
        "global."
    ]
    # Both together: nothing breaks.
    plan = ctx.record_svc.plan_move("archive", ids=[str(tag.id), str(note.id)])
    assert plan.can_move and plan.records == 2
    # A global target can be referenced from anywhere.
    ctx.dataset_svc.update("archive", scope="global")
    ctx.commit()
    assert ctx.record_svc.plan_move("archive", ids=[str(tag.id)]).can_move


def test_a_uniqueness_key_already_taken_there_refuses_the_move(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("site", fields=[("code", "string")])
    ctx.schema_svc.set_unique_keys("site", [["code"]])
    make_collection("survey")
    make_collection("archive")
    a = make_record("survey", "site", {"code": "A"})
    make_record("archive", "site", {"code": "A"})
    b = make_record("survey", "site", {"code": "B"})

    plan = ctx.record_svc.plan_move("archive", ids=[str(a.id)])
    assert len(plan.problems) == 1 and "same code already exists" in plan.problems[0]
    assert ctx.record_svc.plan_move("archive", ids=[str(b.id)]).can_move


def test_two_chosen_records_sharing_a_key_cannot_land_in_one_place(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("site", fields=[("code", "string")])
    ctx.schema_svc.set_unique_keys("site", [["code"]])
    make_schema("visit", fields=[("code", "string")], parent="site")
    ctx.schema_svc.set_unique_keys("visit", [["code"]])
    make_collection("survey")
    s1 = make_record("survey", "site", {"code": "A"})
    s2 = make_record("survey", "site", {"code": "B"})
    v1 = make_record("survey", "visit", {"code": "v"}, parent_record_id=str(s1.id))
    v2 = make_record("survey", "visit", {"code": "v"}, parent_record_id=str(s2.id))
    s3 = make_record("survey", "site", {"code": "C"})

    plan = ctx.record_svc.plan_move("survey", str(s3.id), ids=[str(v1.id), str(v2.id)])
    assert any(
        "Two of the chosen Visit records share the same code" in p
        for p in plan.problems
    )


def test_moving_everything_a_query_lists(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, visit, sample = _tree(ctx, make_schema, make_collection, make_record)
    make_record("survey", "site", {"name": "b"})

    result = ctx.record_svc.move(
        "archive", query=RecordQuery(dataset="survey", schema="site")
    )
    ctx.commit()
    assert (result.roots, result.records) == (2, 4)
    assert ctx.dataset_svc.get("archive").record_count == 4


def test_a_child_chosen_with_its_parent_moves_once(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, visit, _ = _tree(ctx, make_schema, make_collection, make_record)
    plan = ctx.record_svc.plan_move("archive", ids=[str(visit.id), str(site.id)])
    assert (plan.roots, plan.records) == (1, 3)


def test_moving_needs_delete_where_they_are_and_write_where_they_go(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, _, _ = _tree(ctx, make_schema, make_collection, make_record)
    survey = ctx.dataset_svc.get("survey").id
    archive = ctx.dataset_svc.get("archive").id
    svc = ctx.record_svc
    original = svc._permissions
    try:
        svc._permissions = Permissions.of(
            "read", "write_records", collections=[archive]
        )
        with pytest.raises(NotAllowedError):
            svc.plan_move("archive", ids=[str(site.id)])
        svc._permissions = Permissions.of(
            "read", "write_records", "delete", collections=[archive, survey]
        )
        assert svc.plan_move("archive", ids=[str(site.id)]).can_move
    finally:
        svc._permissions = original
