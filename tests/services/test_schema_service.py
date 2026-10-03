"""SchemaService.collect_fields() inheritance behavior."""

from __future__ import annotations

from civex.context import AppContext


def test_collect_fields_includes_own_fields_only_for_root_schema(
    ctx: AppContext, make_schema
):
    schema = make_schema("base", fields=[("subject", "string")])
    resolved = ctx.schema_svc.collect_fields(schema)
    assert [rf.field.name for rf in resolved] == ["subject"]
    assert resolved[0].source_schema_name == "base"


def test_collect_fields_appends_parent_fields_after_own(ctx: AppContext, make_schema):
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.schema_svc.add_field("child", "notes", "string")
    ctx.commit()

    child = ctx.schema_svc.get("child")
    resolved = ctx.schema_svc.collect_fields(child)
    names = [rf.field.name for rf in resolved]
    assert names == ["notes", "subject"]  # own fields first, then inherited
    assert resolved[0].source_schema_name == "child"
    assert resolved[1].source_schema_name == "base"


def test_collect_fields_own_field_shadows_parent_field_of_same_name(
    ctx: AppContext, make_schema
):
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.schema_svc.add_field(
        "child", "subject", "integer"
    )  # same name, different dtype
    ctx.commit()

    child = ctx.schema_svc.get("child")
    resolved = ctx.schema_svc.collect_fields(child)
    subject_fields = [rf for rf in resolved if rf.field.name == "subject"]
    assert len(subject_fields) == 1
    assert subject_fields[0].field.dtype == "integer"
    assert subject_fields[0].source_schema_name == "child"


def test_collect_fields_resolves_multi_level_inheritance(ctx: AppContext, make_schema):
    make_schema("grandparent", fields=[("site", "string")])
    ctx.schema_svc.create("parent", parent="grandparent")
    ctx.schema_svc.add_field("parent", "subject", "string")
    ctx.schema_svc.create("child", parent="parent")
    ctx.schema_svc.add_field("child", "visit_date", "date")
    ctx.commit()

    child = ctx.schema_svc.get("child")
    resolved = ctx.schema_svc.collect_fields(child)
    names = [rf.field.name for rf in resolved]
    assert names == ["visit_date", "subject", "site"]


def test_name_to_id_map_includes_inherited_fields(ctx: AppContext, make_schema):
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.commit()

    child = ctx.schema_svc.get("child")
    name_map = ctx.schema_svc.name_to_id_map(child)
    assert "subject" in name_map
