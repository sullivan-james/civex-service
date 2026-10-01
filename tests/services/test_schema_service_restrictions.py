"""SchemaService restriction-key validation.

Regression: a field could previously be created/updated with a restrictions
dict containing keys RecordService._check_restrictions() doesn't recognize
(e.g. {"format": ".wav"} on a file field) -- the write would succeed, but
the restriction would silently have zero effect at record-write time,
making the field look constrained in the UI while enforcing nothing.
"""
from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import ValidationError


def test_add_field_rejects_unknown_restriction_key(ctx: AppContext, make_schema):
    make_schema("recording")
    with pytest.raises(ValidationError, match="format"):
        ctx.schema_svc.add_field(
            "recording", "recording_file", "file", restrictions={"format": ".wav"}
        )


def test_add_field_accepts_correct_accept_key(ctx: AppContext, make_schema):
    make_schema("recording")
    field = ctx.schema_svc.add_field(
        "recording", "recording_file", "file", restrictions={"accept": ".wav"}
    )
    assert field.restrictions == {"accept": ".wav"}


def test_add_field_rejects_restriction_key_valid_for_a_different_dtype(ctx: AppContext, make_schema):
    """'choices' is valid for string/enum, not integer -- must still be rejected."""
    make_schema("trial")
    with pytest.raises(ValidationError, match="choices"):
        ctx.schema_svc.add_field(
            "trial", "age", "integer", restrictions={"choices": [1, 2, 3]}
        )


def test_update_field_rejects_unknown_restriction_key(ctx: AppContext, make_schema):
    make_schema("recording", fields=[("recording_file", "file")])
    with pytest.raises(ValidationError, match="format"):
        ctx.schema_svc.update_field(
            "recording", "recording_file", restrictions={"format": ".wav"}
        )


def test_update_field_accepts_correct_key(ctx: AppContext, make_schema):
    make_schema("recording", fields=[("recording_file", "file")])
    field = ctx.schema_svc.update_field(
        "recording", "recording_file", restrictions={"accept": ".wav", "max_size": 1000}
    )
    assert field.restrictions == {"accept": ".wav", "max_size": 1000}


def test_boolean_field_rejects_any_restriction_key(ctx: AppContext, make_schema):
    make_schema("trial")
    with pytest.raises(ValidationError, match="min"):
        ctx.schema_svc.add_field("trial", "is_enrolled", "boolean", restrictions={"min": 1})


# ---------------------------------------------------------------------------
# filename_template: references must resolve to fields on the schema
# ---------------------------------------------------------------------------


def test_add_field_accepts_filename_template_referencing_known_field(
    ctx: AppContext, make_schema
):
    make_schema("invoice", fields=[("invoice_number", "string")])
    field = ctx.schema_svc.add_field(
        "invoice",
        "scan",
        "file",
        restrictions={"filename_template": "{invoice_number}.{ext}"},
    )
    assert field.restrictions == {"filename_template": "{invoice_number}.{ext}"}


def test_add_field_accepts_filename_template_using_only_reserved_ext_token(
    ctx: AppContext, make_schema
):
    make_schema("invoice")
    field = ctx.schema_svc.add_field(
        "invoice", "scan", "file", restrictions={"filename_template": "scan.{ext}"}
    )
    assert field.restrictions == {"filename_template": "scan.{ext}"}


def test_add_field_rejects_filename_template_referencing_unknown_field(
    ctx: AppContext, make_schema
):
    make_schema("invoice", fields=[("invoice_number", "string")])
    with pytest.raises(ValidationError, match="nonexistent_field"):
        ctx.schema_svc.add_field(
            "invoice",
            "scan",
            "file",
            restrictions={"filename_template": "{nonexistent_field}.{ext}"},
        )


def test_add_field_rejects_filename_template_on_file_list(ctx: AppContext, make_schema):
    make_schema("invoice", fields=[("invoice_number", "string")])
    with pytest.raises(ValidationError, match="missing_field"):
        ctx.schema_svc.add_field(
            "invoice",
            "scans",
            "file_list",
            restrictions={"filename_template": "{missing_field}.{ext}"},
        )


def test_update_field_rejects_filename_template_referencing_unknown_field(
    ctx: AppContext, make_schema
):
    make_schema(
        "invoice", fields=[("invoice_number", "string"), ("scan", "file")]
    )
    with pytest.raises(ValidationError, match="nope"):
        ctx.schema_svc.update_field(
            "invoice", "scan", restrictions={"filename_template": "{nope}.{ext}"}
        )


def test_update_field_accepts_filename_template_referencing_known_field(
    ctx: AppContext, make_schema
):
    make_schema(
        "invoice", fields=[("invoice_number", "string"), ("scan", "file")]
    )
    field = ctx.schema_svc.update_field(
        "invoice",
        "scan",
        restrictions={"filename_template": "{invoice_number}.{ext}"},
    )
    assert field.restrictions == {"filename_template": "{invoice_number}.{ext}"}


# --- unit / precision / geo ------------------------------------------------

def test_float_unit_is_accepted_and_canonicalised(ctx: AppContext, make_schema):
    make_schema("dive")
    field = ctx.schema_svc.add_field(
        "dive", "depth", "float", restrictions={"unit": "degC", "min": 0}
    )
    assert field.restrictions == {"unit": "°C", "min": 0}


def test_unit_is_only_valid_on_float(ctx: AppContext, make_schema):
    make_schema("dive")
    with pytest.raises(ValidationError, match="unit"):
        ctx.schema_svc.add_field("dive", "count", "integer", restrictions={"unit": "m"})


def test_unit_must_be_a_short_symbol(ctx: AppContext, make_schema):
    make_schema("dive")
    with pytest.raises(ValidationError, match="unit"):
        ctx.schema_svc.add_field(
            "dive", "depth", "float", restrictions={"unit": "metres below surface"}
        )


def test_date_precision_and_partial_bounds(ctx: AppContext, make_schema):
    make_schema("deployment")
    field = ctx.schema_svc.add_field(
        "deployment", "deployed", "date", restrictions={"precision": "month", "min": "2020-01"}
    )
    assert field.restrictions["precision"] == "month"
    with pytest.raises(ValidationError, match="precision"):
        ctx.schema_svc.add_field(
            "deployment", "retrieved", "date", restrictions={"precision": "week"}
        )
    with pytest.raises(ValidationError, match="'max'"):
        ctx.schema_svc.add_field(
            "deployment", "lost", "date", restrictions={"max": "next spring"}
        )


def test_geo_field_and_its_restrictions(ctx: AppContext, make_schema):
    make_schema("deployment")
    field = ctx.schema_svc.add_field(
        "deployment",
        "release_point",
        "geo",
        restrictions={"geometry_types": ["Point"], "bbox": [-12, 48, 4, 62]},
    )
    assert field.dtype == "geo"
    assert field.restrictions["bbox"] == [-12.0, 48.0, 4.0, 62.0]


def test_geo_rejects_bad_geometry_types_and_bbox(ctx: AppContext, make_schema):
    make_schema("deployment")
    with pytest.raises(ValidationError, match="geometry_types"):
        ctx.schema_svc.add_field(
            "deployment", "p", "geo", restrictions={"geometry_types": ["Circle"]}
        )
    with pytest.raises(ValidationError, match="bbox"):
        ctx.schema_svc.add_field("deployment", "q", "geo", restrictions={"bbox": [1, 2, 3]})
