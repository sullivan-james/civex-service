"""CIVEX-172: schemas.display_fields referential integrity.

display_fields is an ordered list of field names (own or inherited) used to
build a record's natural name. Entries are validated at write time and kept
in sync when the field they name is renamed or deleted -- including through
inheritance, and respecting name-shadowing (an inherited field shadowed by a
closer schema's own field of the same name).
"""
from __future__ import annotations

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError
import pytest


def test_update_accepts_known_field_name(ctx: AppContext, make_schema) -> None:
    make_schema("trial", fields=[("subject", "string"), ("site", "string")])
    updated = ctx.schema_svc.update("trial", display_fields=["subject", "site"])
    assert updated.display_fields == ["subject", "site"]


def test_update_accepts_inherited_field_name(ctx: AppContext, make_schema) -> None:
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.commit()

    updated = ctx.schema_svc.update("child", display_fields=["subject"])
    assert updated.display_fields == ["subject"]


def test_update_rejects_unknown_field_name(ctx: AppContext, make_schema) -> None:
    make_schema("trial", fields=[("subject", "string")])
    with pytest.raises(NotFoundError):
        ctx.schema_svc.update("trial", display_fields=["ghost"])


def test_update_rejects_one_unknown_entry_among_valid_ones(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("subject", "string"), ("site", "string")])
    with pytest.raises(NotFoundError):
        ctx.schema_svc.update("trial", display_fields=["subject", "ghost"])


def test_update_empty_list_clears_display_fields(ctx: AppContext, make_schema) -> None:
    make_schema("trial", fields=[("subject", "string")])
    ctx.schema_svc.update("trial", display_fields=["subject"])
    ctx.commit()

    updated = ctx.schema_svc.update("trial", display_fields=[])
    assert updated.display_fields == []


def test_rename_field_updates_single_entry_display_fields(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("subject", "string")])
    ctx.schema_svc.update("trial", display_fields=["subject"])
    ctx.commit()

    ctx.schema_svc.update_field("trial", "subject", new_name="participant")
    ctx.commit()

    assert ctx.schema_svc.get("trial").display_fields == ["participant"]


def test_rename_field_updates_only_its_entry_in_multi_entry_display_fields(
    ctx: AppContext, make_schema
) -> None:
    make_schema(
        "trial",
        fields=[("first_name", "string"), ("last_name", "string"), ("site", "string")],
    )
    ctx.schema_svc.update("trial", display_fields=["first_name", "last_name"])
    ctx.commit()

    ctx.schema_svc.update_field("trial", "last_name", new_name="surname")
    ctx.commit()

    assert ctx.schema_svc.get("trial").display_fields == ["first_name", "surname"]


def test_delete_field_clears_single_entry_display_fields(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("subject", "string")])
    ctx.schema_svc.update("trial", display_fields=["subject"])
    ctx.commit()

    ctx.schema_svc.delete_field("trial", "subject")
    ctx.commit()

    assert ctx.schema_svc.get("trial").display_fields == []


def test_delete_field_removes_only_its_entry_from_multi_entry_display_fields(
    ctx: AppContext, make_schema
) -> None:
    make_schema(
        "trial",
        fields=[("first_name", "string"), ("last_name", "string")],
    )
    ctx.schema_svc.update("trial", display_fields=["first_name", "last_name"])
    ctx.commit()

    ctx.schema_svc.delete_field("trial", "first_name")
    ctx.commit()

    assert ctx.schema_svc.get("trial").display_fields == ["last_name"]


def test_rename_inherited_field_propagates_to_child_display_fields(
    ctx: AppContext, make_schema
) -> None:
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.commit()
    ctx.schema_svc.update("child", display_fields=["subject"])
    ctx.commit()

    ctx.schema_svc.update_field("base", "subject", new_name="participant")
    ctx.commit()

    assert ctx.schema_svc.get("child").display_fields == ["participant"]


def test_delete_inherited_field_propagates_to_child_display_fields(
    ctx: AppContext, make_schema
) -> None:
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.commit()
    ctx.schema_svc.update("child", display_fields=["subject"])
    ctx.commit()

    ctx.schema_svc.delete_field("base", "subject")
    ctx.commit()

    assert ctx.schema_svc.get("child").display_fields == []


def test_rename_shadowed_parent_field_does_not_affect_child_display_fields(
    ctx: AppContext, make_schema
) -> None:
    """child's own 'subject' field shadows base's 'subject' -- child's
    display_fields entry actually resolves to child's own field, so renaming
    base's field must leave the child's display_fields untouched."""
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.schema_svc.add_field("child", "subject", "string")  # shadows base.subject
    ctx.commit()
    ctx.schema_svc.update("child", display_fields=["subject"])
    ctx.commit()

    ctx.schema_svc.update_field("base", "subject", new_name="participant")
    ctx.commit()

    # child's entry still names its own (unrenamed) field
    assert ctx.schema_svc.get("child").display_fields == ["subject"]


def test_delete_shadowed_parent_field_does_not_affect_child_display_fields(
    ctx: AppContext, make_schema
) -> None:
    make_schema("base", fields=[("subject", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.schema_svc.add_field("child", "subject", "string")  # shadows base.subject
    ctx.commit()
    ctx.schema_svc.update("child", display_fields=["subject"])
    ctx.commit()

    ctx.schema_svc.delete_field("base", "subject")
    ctx.commit()

    assert ctx.schema_svc.get("child").display_fields == ["subject"]


def test_rename_field_does_not_affect_unrelated_schema(
    ctx: AppContext, make_schema
) -> None:
    make_schema("trial", fields=[("subject", "string")])
    make_schema("other", fields=[("subject", "string")])
    ctx.schema_svc.update("trial", display_fields=["subject"])
    ctx.schema_svc.update("other", display_fields=["subject"])
    ctx.commit()

    ctx.schema_svc.update_field("trial", "subject", new_name="participant")
    ctx.commit()

    assert ctx.schema_svc.get("trial").display_fields == ["participant"]
    assert ctx.schema_svc.get("other").display_fields == ["subject"]
