"""schemas.display_template referential integrity.

The template names the variables it uses (own or inherited fields). It is
validated at write time and kept in sync when a field it mentions is renamed
or deleted -- including through inheritance, and respecting name-shadowing
(an inherited field shadowed by a closer schema's own field of the same name).
"""
from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import ValidationError


def test_update_accepts_known_fields_and_builtins(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("subject", "string"), ("site", "string")])
    updated = ctx.schema_svc.update(
        "trial", display_template="{schema}: {subject:upper} @ {site}"
    )
    assert updated.display_template == "{schema}: {subject:upper} @ {site}"


def test_update_accepts_inherited_field_name(ctx: AppContext, make_schema) -> None:
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.commit()

    updated = ctx.schema_svc.update("child", display_template="{subject}")
    assert updated.display_template == "{subject}"


@pytest.mark.parametrize("bad", ["{ghost}", "{subject} {ghost}", "{subject", "{subject:nope}"])
def test_update_rejects_bad_templates(ctx: AppContext, make_schema, bad) -> None:
    make_schema("trial", fields=[("subject", "string")])
    with pytest.raises(ValidationError):
        ctx.schema_svc.update("trial", display_template=bad)


def test_update_rejects_ext_in_a_record_name(ctx: AppContext, make_schema) -> None:
    make_schema("trial", fields=[("subject", "string")])
    with pytest.raises(ValidationError):
        ctx.schema_svc.update("trial", display_template="{subject}.{ext}")


def test_update_empty_string_clears_the_template(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("subject", "string")])
    ctx.schema_svc.update("trial", display_template="{subject}")
    ctx.commit()

    updated = ctx.schema_svc.update("trial", display_template="")
    assert updated.display_template is None


def test_rename_field_rewrites_the_template_keeping_formats(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("first_name", "string"), ("last_name", "string")])
    ctx.schema_svc.update("trial", display_template="{first_name} {last_name:upper}")
    ctx.commit()

    ctx.schema_svc.update_field("trial", "last_name", new_name="surname")
    ctx.commit()

    assert (
        ctx.schema_svc.get("trial").display_template == "{first_name} {surname:upper}"
    )


def test_delete_field_removes_its_variable_and_separator(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("first_name", "string"), ("last_name", "string")])
    ctx.schema_svc.update("trial", display_template="{first_name} - {last_name}")
    ctx.commit()

    ctx.schema_svc.delete_field("trial", "first_name")
    ctx.commit()

    assert ctx.schema_svc.get("trial").display_template == "{last_name}"


def test_delete_last_variable_clears_the_template(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("subject", "string")])
    ctx.schema_svc.update("trial", display_template="{subject}")
    ctx.commit()

    ctx.schema_svc.delete_field("trial", "subject")
    ctx.commit()

    assert ctx.schema_svc.get("trial").display_template is None


def test_rename_inherited_field_propagates_to_child_template(
    ctx: AppContext, make_schema
) -> None:
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.commit()
    ctx.schema_svc.update("child", display_template="{subject}")
    ctx.commit()

    ctx.schema_svc.update_field("base", "subject", new_name="participant")
    ctx.commit()

    assert ctx.schema_svc.get("child").display_template == "{participant}"


def test_delete_inherited_field_propagates_to_child_template(
    ctx: AppContext, make_schema
) -> None:
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.commit()
    ctx.schema_svc.update("child", display_template="{subject}")
    ctx.commit()

    ctx.schema_svc.delete_field("base", "subject")
    ctx.commit()

    assert ctx.schema_svc.get("child").display_template is None


def test_shadowed_parent_field_changes_do_not_touch_child_template(
    ctx: AppContext, make_schema
) -> None:
    """child's own 'subject' shadows base's, so the child's template resolves
    to its own field: renaming or deleting base's must leave it alone."""
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.schema_svc.add_field("child", "subject", "string")
    ctx.commit()
    ctx.schema_svc.update("child", display_template="{subject}")
    ctx.commit()

    ctx.schema_svc.update_field("base", "subject", new_name="participant")
    ctx.commit()
    assert ctx.schema_svc.get("child").display_template == "{subject}"

    ctx.schema_svc.delete_field("base", "participant")
    ctx.commit()
    assert ctx.schema_svc.get("child").display_template == "{subject}"


def test_rename_does_not_affect_unrelated_schema(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("subject", "string")])
    make_schema("other", fields=[("subject", "string")])
    ctx.schema_svc.update("trial", display_template="{subject}")
    ctx.schema_svc.update("other", display_template="{subject}")
    ctx.commit()

    ctx.schema_svc.update_field("trial", "subject", new_name="participant")
    ctx.commit()

    assert ctx.schema_svc.get("trial").display_template == "{participant}"
    assert ctx.schema_svc.get("other").display_template == "{subject}"


def test_rename_and_delete_rewrite_filename_templates(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("site", "string"), ("year", "integer")])
    ctx.schema_svc.add_field(
        "trial",
        "scan",
        "file",
        restrictions={"filename_template": "{site}_{year}.{ext}"},
    )
    ctx.commit()

    ctx.schema_svc.update_field("trial", "site", new_name="location")
    ctx.commit()
    scan = next(f for f in ctx.schema_svc.get("trial").fields if f.name == "scan")
    assert scan.restrictions["filename_template"] == "{location}_{year}.{ext}"

    ctx.schema_svc.delete_field("trial", "year")
    ctx.commit()
    scan = next(f for f in ctx.schema_svc.get("trial").fields if f.name == "scan")
    assert scan.restrictions["filename_template"] == "{location}.{ext}"


def _site_and_sample(ctx: AppContext, make_schema) -> None:
    make_schema("site", fields=[("name", "string"), ("code", "string")])
    make_schema("sample", fields=[("n", "integer")])
    ctx.schema_svc.add_field(
        "sample", "site", "reference", restrictions={"schema": "site"}
    )
    ctx.commit()


def test_template_may_reach_a_field_of_the_referenced_schema(
    ctx: AppContext, make_schema
) -> None:
    _site_and_sample(ctx, make_schema)
    updated = ctx.schema_svc.update("sample", display_template="{site.code}-{n}")
    assert updated.display_template == "{site.code}-{n}"


@pytest.mark.parametrize("bad", ["{site.ghost}", "{n.x}", "{nope.code}"])
def test_template_rejects_a_bad_reference_path(
    ctx: AppContext, make_schema, bad
) -> None:
    _site_and_sample(ctx, make_schema)
    with pytest.raises(ValidationError):
        ctx.schema_svc.update("sample", display_template=bad)


def test_reference_without_a_target_schema_cannot_be_reached(
    ctx: AppContext, make_schema
) -> None:
    make_schema("sample", fields=[("n", "integer")])
    ctx.schema_svc.add_field("sample", "anything", "reference")
    ctx.commit()
    with pytest.raises(ValidationError):
        ctx.schema_svc.update("sample", display_template="{anything.x}")


def test_file_names_cannot_reach_other_records(ctx: AppContext, make_schema) -> None:
    _site_and_sample(ctx, make_schema)
    with pytest.raises(ValidationError):
        ctx.schema_svc.add_field(
            "sample",
            "scan",
            "file",
            restrictions={"filename_template": "{site.code}.{ext}"},
        )


def test_renaming_the_reference_field_rewrites_the_path(
    ctx: AppContext, make_schema
) -> None:
    _site_and_sample(ctx, make_schema)
    ctx.schema_svc.update("sample", display_template="{site.code}-{n}")
    ctx.commit()
    ctx.schema_svc.update_field("sample", "site", new_name="place")
    ctx.commit()
    assert ctx.schema_svc.get("sample").display_template == "{place.code}-{n}"


def test_renaming_a_field_of_the_referenced_schema_rewrites_the_path(
    ctx: AppContext, make_schema
) -> None:
    _site_and_sample(ctx, make_schema)
    ctx.schema_svc.update("sample", display_template="{site.code}-{n}")
    ctx.commit()
    ctx.schema_svc.update_field("site", "code", new_name="short_code")
    ctx.commit()
    assert ctx.schema_svc.get("sample").display_template == "{site.short_code}-{n}"


def test_deleting_a_field_of_the_referenced_schema_drops_the_path(
    ctx: AppContext, make_schema
) -> None:
    _site_and_sample(ctx, make_schema)
    ctx.schema_svc.update("sample", display_template="{site.code}-{n}")
    ctx.commit()
    ctx.schema_svc.delete_field("site", "code")
    ctx.commit()
    assert ctx.schema_svc.get("sample").display_template == "{n}"


def test_deleting_the_reference_field_drops_its_paths(
    ctx: AppContext, make_schema
) -> None:
    _site_and_sample(ctx, make_schema)
    ctx.schema_svc.update("sample", display_template="{site.code}-{n}")
    ctx.commit()
    ctx.schema_svc.delete_field("sample", "site")
    ctx.commit()
    assert ctx.schema_svc.get("sample").display_template == "{n}"


# --- a new schema starts with a visible template ---


def test_first_nameable_field_becomes_the_template(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("subject", "string"), ("site", "string")])
    assert ctx.schema_svc.get("trial").display_template == "{subject}"


def test_fields_that_cannot_be_named_are_skipped(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("where", "geo"), ("scan", "file")])
    assert ctx.schema_svc.get("trial").display_template is None

    ctx.schema_svc.add_field("trial", "subject", "string")
    assert ctx.schema_svc.get("trial").display_template == "{subject}"


def test_an_existing_template_is_left_alone(ctx: AppContext, make_schema) -> None:
    make_schema("trial", fields=[("subject", "string"), ("site", "string")])
    ctx.schema_svc.update("trial", display_template="{site}")
    ctx.schema_svc.add_field("trial", "notes", "string")
    assert ctx.schema_svc.get("trial").display_template == "{site}"


def test_a_cleared_template_is_not_refilled(ctx: AppContext, make_schema) -> None:
    make_schema("trial", fields=[("subject", "string")])
    ctx.schema_svc.update("trial", display_template="")
    ctx.schema_svc.add_field("trial", "site", "string")
    assert ctx.schema_svc.get("trial").display_template is None


def test_a_child_schema_starts_from_its_own_first_field(
    ctx: AppContext, make_schema
) -> None:
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.schema_svc.add_field("child", "depth", "float")
    assert ctx.schema_svc.get("child").display_template == "{depth}"


def test_create_with_fields_names_the_schema(ctx: AppContext) -> None:
    schema = ctx.schema_svc.create_with_fields(
        "trial", fields=[{"name": "subject", "type": "string"}]
    )
    assert schema.display_template == "{subject}"


def test_auto_name_can_be_turned_off(ctx: AppContext, make_schema) -> None:
    make_schema("trial")
    ctx.schema_svc.add_field("trial", "subject", "string", auto_name=False)
    assert ctx.schema_svc.get("trial").display_template is None


def test_the_automatic_template_is_recorded_in_the_audit_log(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial")
    ctx.schema_svc.add_field("trial", "subject", "string")
    ctx.commit()
    schema = ctx.schema_svc.get("trial")
    entries = ctx.audit_svc.list_audit(entity_id=schema.id)
    assert any(
        e.action == "update"
        and (e.new_data or {}).get("display_template") == "{subject}"
        for e in entries
    )
