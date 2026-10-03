"""SchemaService.delete() soft-deletes a schema and the records typed by it,
but leaves schemas that inherit from it (and their own records) alone --
see SchemaRepository.delete() and docs/guides/deleting-and-restoring.md.
get_delete_impact() reports that same record count up front, plus an
informational count of inheriting descendant schemas -- not deleted with
it, but what blocks a later purge().

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


def test_impact_is_zero_for_a_schema_with_no_dependents(ctx: AppContext, make_schema):
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


def test_impact_reports_descendant_schema_count_and_own_record_count(
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
    assert impact.record_count == 1


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


def test_delete_leaves_child_schemas_and_their_records_untouched(
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
    assert ctx.schema_svc.get("derived")
    assert _record_gone(ctx, base_record.id)
    assert not _record_gone(ctx, derived_record.id)


def test_delete_leaves_multi_level_descendants_and_their_records_untouched(
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

    with pytest.raises(NotFoundError):
        ctx.schema_svc.get("base")
    assert ctx.schema_svc.get("derived")
    assert ctx.schema_svc.get("grandchild")
    assert _record_gone(ctx, base.id)
    assert not _record_gone(ctx, derived.id)
    assert not _record_gone(ctx, grandchild.id)


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
