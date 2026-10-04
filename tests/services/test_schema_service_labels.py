"""Slug-validated names and free-text labels on schemas and fields."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import ValidationError


# --- name validation -------------------------------------------------------


def test_create_rejects_a_non_slug_schema_name(ctx: AppContext):
    with pytest.raises(ValidationError) as exc:
        ctx.schema_svc.create("Acoustic Recording")
    assert "acoustic_recording" in str(exc.value)


def test_add_field_rejects_a_non_slug_field_name(ctx: AppContext, make_schema):
    make_schema("trial")
    with pytest.raises(ValidationError):
        ctx.schema_svc.add_field("trial", "Recording Date", "date")


def test_rename_to_a_non_slug_name_is_rejected(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    with pytest.raises(ValidationError):
        ctx.schema_svc.update("trial", new_name="Trial Runs")
    with pytest.raises(ValidationError):
        ctx.schema_svc.update_field("trial", "subject", new_name="Subject Name")


def test_a_rejected_name_leaves_nothing_behind(ctx: AppContext):
    with pytest.raises(ValidationError):
        ctx.schema_svc.create("Bad Name")
    ctx.commit()
    assert [s.name for s in ctx.schema_svc.list_all()] == []


def test_restore_paths_may_keep_legacy_names(ctx: AppContext):
    """Dumps taken before slug validation must restore byte-for-byte —
    slugifying them would break the workflow YAML in the same dump."""
    ctx.schema_svc.create("Legacy Schema", allow_legacy_name=True)
    ctx.schema_svc.add_field(
        "Legacy Schema", "Legacy Field", "string", allow_legacy_name=True
    )
    ctx.commit()
    schema = ctx.schema_svc.get("Legacy Schema")
    assert [f.name for f in schema.fields] == ["Legacy Field"]


# --- labels ----------------------------------------------------------------


def test_label_is_stored_and_read_back(ctx: AppContext):
    ctx.schema_svc.create("acoustic_recording", label="Acoustic Recording")
    ctx.schema_svc.add_field(
        "acoustic_recording", "recording_date", "date", label="Date of Recording"
    )
    ctx.commit()

    schema = ctx.schema_svc.get("acoustic_recording")
    assert schema.label == "Acoustic Recording"
    assert schema.fields[0].label == "Date of Recording"


def test_label_defaults_to_none_and_display_name_derives_one(
    ctx: AppContext, make_schema
):
    make_schema("acoustic_recording", fields=[("recording_date", "date")])
    schema = ctx.schema_svc.get("acoustic_recording")
    assert schema.label is None
    assert schema.display_name == "Acoustic Recording"
    assert schema.fields[0].display_name == "Recording Date"


def test_label_can_be_changed_without_touching_the_name(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    ctx.schema_svc.update("trial", label="Clinical Trial")
    ctx.schema_svc.update_field("trial", "subject", label="Subject ID")
    ctx.commit()

    schema = ctx.schema_svc.get("trial")
    assert (schema.name, schema.label) == ("trial", "Clinical Trial")
    assert (schema.fields[0].name, schema.fields[0].label) == ("subject", "Subject ID")


def test_empty_label_clears_it_back_to_the_derived_one(ctx: AppContext):
    ctx.schema_svc.create("trial", label="Clinical Trial")
    ctx.schema_svc.add_field("trial", "subject", "string", label="Subject ID")
    ctx.commit()

    ctx.schema_svc.update("trial", label="")
    ctx.schema_svc.update_field("trial", "subject", label="")
    ctx.commit()

    schema = ctx.schema_svc.get("trial")
    assert schema.label is None
    assert schema.display_name == "Trial"
    assert schema.fields[0].label is None


def test_omitting_label_leaves_it_untouched(ctx: AppContext):
    ctx.schema_svc.create("trial", label="Clinical Trial")
    ctx.schema_svc.add_field("trial", "subject", "string", label="Subject ID")
    ctx.commit()

    ctx.schema_svc.update("trial", description="Updated")
    ctx.schema_svc.update_field("trial", "subject", required=True)
    ctx.commit()

    schema = ctx.schema_svc.get("trial")
    assert schema.label == "Clinical Trial"
    assert schema.fields[0].label == "Subject ID"


def test_two_schemas_may_share_a_label(ctx: AppContext):
    """Labels are presentation, not identity — only names are unique."""
    ctx.schema_svc.create("trial_v1", label="Trial")
    ctx.schema_svc.create("trial_v2", label="Trial")
    ctx.commit()
    assert len(ctx.schema_svc.list_all()) == 2


# --- lint ------------------------------------------------------------------


def test_lint_reports_nothing_for_a_clean_project(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    assert ctx.schema_svc.lint_names() == []


def test_lint_reports_legacy_names_with_suggestions(ctx: AppContext):
    ctx.schema_svc.create("Legacy Schema", allow_legacy_name=True)
    ctx.schema_svc.add_field(
        "Legacy Schema", "Legacy Field", "string", allow_legacy_name=True
    )
    ctx.schema_svc.add_field("Legacy Schema", "fine_field", "string")
    ctx.commit()

    issues = ctx.schema_svc.lint_names()
    assert {(i.kind, i.name, i.suggestion) for i in issues} == {
        ("schema", "Legacy Schema", "legacy_schema"),
        ("field", "Legacy Field", "legacy_field"),
    }
    assert all(i.schema_name == "Legacy Schema" for i in issues)
