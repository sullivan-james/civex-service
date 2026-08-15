"""SchemaService.delete() cascades to descendant schemas and their records;
get_delete_impact() reports the same counts up front so the UI can warn
before the delete happens.

A record can only carry a parent_record_id if its own schema inherits from
its parent's -- RecordService.add() requires and validates this -- so the
record hierarchy always mirrors the schema hierarchy; there's no way for a
record of an unrelated schema to end up nested under one of these.
"""
from __future__ import annotations

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError
import pytest


def _record_gone(ctx: AppContext, record_id) -> bool:
    try:
        ctx.record_svc.get(str(record_id))
        return False
    except NotFoundError:
        return True


def test_impact_is_zero_for_a_schema_with_no_dependents(
    ctx: AppContext, make_schema
):
    make_schema("trial")
    impact = ctx.schema_svc.get_delete_impact("trial")
    assert impact.child_schema_count == 0
    assert impact.record_count == 0


def test_impact_counts_records_of_the_schema_itself(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("trial")
    make_collection("study")
    make_record("study", "trial", {})
    make_record("study", "trial", {})

    impact = ctx.schema_svc.get_delete_impact("trial")
    assert impact.child_schema_count == 0
    assert impact.record_count == 2


def test_impact_counts_inheriting_child_schemas_and_their_records(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("base")
    make_schema("derived", parent="base")
    make_schema("grandchild", parent="derived")
    make_collection("study")
    base = make_record("study", "base", {})
    derived = make_record("study", "derived", {}, parent_record_id=str(base.id))
    make_record("study", "grandchild", {}, parent_record_id=str(derived.id))

    impact = ctx.schema_svc.get_delete_impact("base")
    assert impact.child_schema_count == 2
    assert impact.record_count == 3


def test_impact_for_a_middle_schema_excludes_its_ancestor(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("base")
    make_schema("derived", parent="base")
    make_collection("study")
    base = make_record("study", "base", {})
    make_record("study", "derived", {}, parent_record_id=str(base.id))

    impact = ctx.schema_svc.get_delete_impact("derived")
    assert impact.child_schema_count == 0
    assert impact.record_count == 1


def test_delete_removes_schema_with_no_dependents(ctx: AppContext, make_schema):
    make_schema("trial")
    ctx.schema_svc.delete("trial")
    ctx.commit()
    with pytest.raises(NotFoundError):
        ctx.schema_svc.get("trial")


def test_delete_cascades_to_records_of_the_schema(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("trial")
    make_collection("study")
    record = make_record("study", "trial", {})

    ctx.schema_svc.delete("trial")
    ctx.commit()

    with pytest.raises(NotFoundError):
        ctx.schema_svc.get("trial")
    assert _record_gone(ctx, record.id)


def test_delete_cascades_to_child_schemas_and_their_records(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("base")
    make_schema("derived", parent="base")
    make_collection("study")
    base_record = make_record("study", "base", {})
    derived_record = make_record(
        "study", "derived", {}, parent_record_id=str(base_record.id)
    )

    ctx.schema_svc.delete("base")
    ctx.commit()

    with pytest.raises(NotFoundError):
        ctx.schema_svc.get("base")
    with pytest.raises(NotFoundError):
        ctx.schema_svc.get("derived")
    assert _record_gone(ctx, base_record.id)
    assert _record_gone(ctx, derived_record.id)


def test_delete_cascades_through_multi_level_inheritance(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("base")
    make_schema("derived", parent="base")
    make_schema("grandchild", parent="derived")
    make_collection("study")
    base = make_record("study", "base", {})
    derived = make_record("study", "derived", {}, parent_record_id=str(base.id))
    grandchild = make_record(
        "study", "grandchild", {}, parent_record_id=str(derived.id)
    )

    ctx.schema_svc.delete("base")
    ctx.commit()

    for name in ("base", "derived", "grandchild"):
        with pytest.raises(NotFoundError):
            ctx.schema_svc.get(name)
    assert _record_gone(ctx, base.id)
    assert _record_gone(ctx, derived.id)
    assert _record_gone(ctx, grandchild.id)


def test_delete_of_a_middle_schema_leaves_its_ancestor_intact(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("base")
    make_schema("derived", parent="base")
    make_collection("study")
    base_record = make_record("study", "base", {})
    derived_record = make_record(
        "study", "derived", {}, parent_record_id=str(base_record.id)
    )

    ctx.schema_svc.delete("derived")
    ctx.commit()

    assert ctx.schema_svc.get("base")
    assert not _record_gone(ctx, base_record.id)
    assert _record_gone(ctx, derived_record.id)


def test_delete_impact_raises_not_found_for_missing_schema(ctx: AppContext):
    with pytest.raises(NotFoundError):
        ctx.schema_svc.get_delete_impact("does-not-exist")


def test_delete_raises_not_found_for_missing_schema(ctx: AppContext):
    with pytest.raises(NotFoundError):
        ctx.schema_svc.delete("does-not-exist")
