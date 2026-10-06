"""Restoring a schema or collection never brings a record back under a parent
that is still deleted: a record can't come back there by its own restore either
(`restore_plan` is blocked by it)."""

from __future__ import annotations

from civex.context import AppContext


def _tree(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("site", fields=[("name", "string")])
    make_schema("visit", fields=[("when", "string")], parent="site")
    make_collection("survey")
    ctx.dataset_svc.update("survey", schemas=["site", "visit"])
    site = make_record("survey", "site", {"name": "a"})
    visit = make_record(
        "survey", "visit", {"when": "may"}, parent_record_id=str(site.id)
    )
    return site, visit


def _deleted(ctx: AppContext, record) -> bool:
    return ctx.record_svc.labels([str(record.id)])[0].deleted_at is not None


def test_a_schema_restore_leaves_a_child_whose_parent_was_deleted_meanwhile(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, visit = _tree(ctx, make_schema, make_collection, make_record)
    ctx.schema_svc.delete("visit")  # the visit goes with its schema
    ctx.record_svc.delete(str(site.id))  # then its parent, on its own
    ctx.commit()
    assert ctx.schema_svc.restore_plan("visit").records == 0

    ctx.schema_svc.restore("visit")
    ctx.commit()

    assert _deleted(ctx, site) and _deleted(ctx, visit)


def test_a_collection_restore_brings_back_a_parent_and_child_deleted_with_it(
    ctx: AppContext, make_schema, make_collection, make_record
):
    site, visit = _tree(ctx, make_schema, make_collection, make_record)
    ctx.dataset_svc.delete("survey")
    ctx.commit()
    ctx.dataset_svc.restore("survey")
    ctx.commit()
    assert not _deleted(ctx, site) and not _deleted(ctx, visit)
