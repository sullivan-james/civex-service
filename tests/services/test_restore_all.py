"""Restoring everything deleted that a history filter matches."""

from __future__ import annotations

import pytest

from civex.context import AppContext


def leaf(field: str, value, op: str = "eq") -> dict:
    return {"field": field, "op": op, "value": value}


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("label", "string")], parent="encounter")
    make_collection("humpback")
    enc = make_record("humpback", "encounter", {"site": "S"})
    recs = [
        make_record(
            "humpback", "recording", {"label": f"R{i}"}, parent_record_id=str(enc.id)
        )
        for i in range(3)
    ]
    other = make_record("humpback", "encounter", {"site": "T"})
    return {"enc": enc, "recs": recs, "other": other}


def _live(ctx: AppContext) -> set:
    return {r.id for r in ctx.record_svc.find("humpback", None)}


def test_a_bulk_delete_comes_back_in_one_go(ctx: AppContext, survey):
    ids = [str(r.id) for r in survey["recs"]]
    ctx.record_svc.delete_many(ids)
    ctx.commit()
    where = {"and": [leaf("under", str(survey["enc"].id))]}

    plan = ctx.history_svc.plan_restore_all(where)
    assert (plan.records, plan.restores, plan.blocked, plan.things) == (3, 3, 0, 3)

    result = ctx.history_svc.restore_all(where)
    ctx.commit()
    assert (result.restored, result.records, result.blocked) == (3, 3, 0)
    assert {r.id for r in survey["recs"]} <= _live(ctx)
    # One event in history, not three.
    events, _ = ctx.history_svc.events(where={"and": [leaf("how", "restore")]})
    assert len(events) == 1 and events[0].batch.label == "Restore all"


def test_a_tree_deleted_together_is_not_counted_twice_nor_called_blocked(
    ctx: AppContext, survey
):
    ctx.record_svc.delete(str(survey["enc"].id))  # the encounter and its recordings
    ctx.commit()
    where = {"and": [leaf("under", str(survey["enc"].id))]}
    plan = ctx.history_svc.plan_restore_all(where)
    assert plan.blocked == 0
    assert plan.restores == 4  # the encounter and three recordings, once each
    result = ctx.history_svc.restore_all(where)
    ctx.commit()
    assert result.records == 4 and result.blocked == 0
    assert len(_live(ctx)) == 5


def test_a_record_left_under_a_deleted_parent_outside_the_set_is_blocked(
    ctx: AppContext, survey
):
    ctx.record_svc.delete(str(survey["enc"].id))
    ctx.commit()
    # Only the recordings are matched; their parent is deleted and not included.
    where = {"and": [leaf("schema", "recording")]}
    plan = ctx.history_svc.plan_restore_all(where)
    assert (plan.blocked, plan.restores) == (3, 0)
    result = ctx.history_svc.restore_all(where)
    ctx.commit()
    assert (result.restored, result.blocked) == (0, 3)
    assert survey["enc"].id not in _live(ctx)


def test_collections_and_schemas_come_back_before_their_records(
    ctx: AppContext, survey
):
    ctx.record_svc.delete(str(survey["recs"][0].id))  # on its own, first
    ctx.dataset_svc.delete("humpback")
    ctx.commit()
    result = ctx.history_svc.restore_all({"and": [leaf("collection", "humpback")]})
    ctx.commit()
    assert result.blocked == 0
    assert survey["other"].id in _live(ctx)  # with the collection
    assert survey["recs"][0].id in _live(ctx)  # then the one deleted earlier


def test_only_what_is_deleted_now_and_was_deleted_counts(ctx: AppContext, survey):
    plan = ctx.history_svc.plan_restore_all({"and": [leaf("collection", "humpback")]})
    assert plan.things == 0  # nothing is deleted
    ctx.record_svc.delete(str(survey["other"].id))
    ctx.record_svc.restore(str(survey["other"].id))
    ctx.commit()
    assert ctx.history_svc.plan_restore_all().things == 0  # back already


def test_the_search_narrows_what_is_restored(ctx: AppContext, survey):
    ctx.record_svc.delete_many([str(r.id) for r in survey["recs"]])
    ctx.commit()
    result = ctx.history_svc.restore_all(None, search="R1")
    ctx.commit()
    assert result.restored == 1
    assert survey["recs"][1].id in _live(ctx)
    assert survey["recs"][0].id not in _live(ctx)
