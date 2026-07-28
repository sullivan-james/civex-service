"""CIVEX-172: natural-name rendering from schemas.display_fields.

display_fields joins each listed field's present value with a space,
skipping entries whose value is missing/empty. An empty display_fields list
falls back to the pre-existing auto-detect behavior (first non-empty scalar
field value).
"""
from __future__ import annotations

from civex.context import AppContext


def test_natural_name_joins_multiple_display_fields(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema(
        "patient", fields=[("first_name", "string"), ("last_name", "string")]
    )
    ctx.schema_svc.update("patient", display_fields=["first_name", "last_name"])
    make_collection("study")
    ctx.commit()

    rec = ctx.record_svc.add(
        "study", "patient", {"first_name": "Ada", "last_name": "Lovelace"}
    )
    ctx.commit()

    assert ctx.record_svc.get(str(rec.id)).natural_name == "Ada Lovelace"


def test_natural_name_skips_missing_display_field_entries(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema(
        "patient", fields=[("first_name", "string"), ("last_name", "string")]
    )
    ctx.schema_svc.update("patient", display_fields=["first_name", "last_name"])
    make_collection("study")
    ctx.commit()

    rec = ctx.record_svc.add("study", "patient", {"first_name": "Ada"})
    ctx.commit()

    assert ctx.record_svc.get(str(rec.id)).natural_name == "Ada"


def test_natural_name_none_when_all_display_fields_missing(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema(
        "patient", fields=[("first_name", "string"), ("last_name", "string")]
    )
    ctx.schema_svc.update("patient", display_fields=["first_name", "last_name"])
    make_collection("study")
    ctx.commit()

    rec = ctx.record_svc.add("study", "patient", {})
    ctx.commit()

    assert ctx.record_svc.get(str(rec.id)).natural_name is None


def test_natural_name_falls_back_to_auto_detect_when_display_fields_empty(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("patient", fields=[("first_name", "string")])
    make_collection("study")
    ctx.commit()

    rec = ctx.record_svc.add("study", "patient", {"first_name": "Ada"})
    ctx.commit()

    assert ctx.record_svc.get(str(rec.id)).natural_name == "Ada"
