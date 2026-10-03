"""Natural-name rendering from schemas.display_template.

The template is rendered over the record's values (domain/templating.py);
a variable with no value is dropped along with the separator beside it. A
schema with no template falls back to the first non-empty scalar field value.
"""
from __future__ import annotations

from civex.context import AppContext


def test_natural_name_renders_the_template(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema(
        "patient", fields=[("first_name", "string"), ("last_name", "string")]
    )
    ctx.schema_svc.update("patient", display_template="{first_name} {last_name}")
    make_collection("study")
    ctx.commit()

    rec = ctx.record_svc.add(
        "study", "patient", {"first_name": "Ada", "last_name": "Lovelace"}
    )
    ctx.commit()

    assert ctx.record_svc.get(str(rec.id)).natural_name == "Ada Lovelace"


def test_natural_name_skips_missing_variables(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema(
        "patient", fields=[("first_name", "string"), ("last_name", "string")]
    )
    ctx.schema_svc.update("patient", display_template="{first_name} {last_name}")
    make_collection("study")
    ctx.commit()

    rec = ctx.record_svc.add("study", "patient", {"first_name": "Ada"})
    ctx.commit()

    assert ctx.record_svc.get(str(rec.id)).natural_name == "Ada"


def test_natural_name_none_when_all_template_missing(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema(
        "patient", fields=[("first_name", "string"), ("last_name", "string")]
    )
    ctx.schema_svc.update("patient", display_template="{first_name} {last_name}")
    make_collection("study")
    ctx.commit()

    rec = ctx.record_svc.add("study", "patient", {})
    ctx.commit()

    assert ctx.record_svc.get(str(rec.id)).natural_name is None


def test_natural_name_falls_back_to_auto_detect_when_no_template(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("patient", fields=[("first_name", "string")])
    make_collection("study")
    ctx.commit()

    rec = ctx.record_svc.add("study", "patient", {"first_name": "Ada"})
    ctx.commit()

    assert ctx.record_svc.get(str(rec.id)).natural_name == "Ada"


def test_natural_name_formats_values_and_uses_builtins(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("sample", fields=[("site", "string"), ("taken_on", "date")])
    ctx.schema_svc.update(
        "sample", display_template="{schema:upper}/{site:slug}/{taken_on:YYYY-MM}"
    )
    make_collection("study")
    ctx.commit()

    rec = ctx.record_svc.add(
        "study", "sample", {"site": "North Ridge", "taken_on": "2019-06-14"}
    )
    ctx.commit()

    assert (
        ctx.record_svc.get(str(rec.id)).natural_name == "SAMPLE/north_ridge/2019-06"
    )


def test_natural_name_uses_the_short_record_id(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("sample", fields=[("site", "string")])
    ctx.schema_svc.update("sample", display_template="{site}-{id}")
    make_collection("study")
    ctx.commit()

    rec = ctx.record_svc.add("study", "sample", {"site": "A"})
    ctx.commit()

    assert ctx.record_svc.get(str(rec.id)).natural_name == f"A-{str(rec.id)[:8]}"


def _site_and_sample(ctx, make_schema, make_collection, template):
    make_schema("site", fields=[("name", "string"), ("code", "string")])
    make_schema("sample", fields=[("n", "integer")])
    ctx.schema_svc.add_field(
        "sample", "site", "reference", restrictions={"schema": "site"}
    )
    ctx.schema_svc.update("sample", display_template=template)
    make_collection("study")
    ctx.commit()
    site = ctx.record_svc.add("study", "site", {"name": "Ridge", "code": "RG"})
    sample = ctx.record_svc.add(
        "study", "sample", {"n": 4, "site": str(site.id)}
    )
    ctx.commit()
    return site, sample


def test_name_can_use_a_field_of_the_referenced_record(
    ctx: AppContext, make_schema, make_collection
) -> None:
    _, sample = _site_and_sample(
        ctx, make_schema, make_collection, "{site.code}-{n:03}"
    )
    assert ctx.record_svc.get(str(sample.id)).natural_name == "RG-004"


def test_referenced_value_is_read_live(
    ctx: AppContext, make_schema, make_collection
) -> None:
    site, sample = _site_and_sample(
        ctx, make_schema, make_collection, "{site.code}-{n:03}"
    )
    ctx.record_svc.update(str(site.id), {"code": "XX"})
    ctx.commit()
    assert ctx.record_svc.get(str(sample.id)).natural_name == "XX-004"


def test_unset_reference_is_skipped(
    ctx: AppContext, make_schema, make_collection
) -> None:
    _, sample = _site_and_sample(
        ctx, make_schema, make_collection, "{site.code}-{n:03}"
    )
    bare = ctx.record_svc.add("study", "sample", {"n": 9})
    ctx.commit()
    assert ctx.record_svc.get(str(bare.id)).natural_name == "009"


def test_listing_names_records_in_one_batch(
    ctx: AppContext, make_schema, make_collection
) -> None:
    _site_and_sample(ctx, make_schema, make_collection, "{site.name}/{n}")
    names = {
        r.natural_name for r in ctx.record_svc.find_by_schema("sample")
    }
    assert names == {"Ridge/4"}
