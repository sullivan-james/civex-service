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
