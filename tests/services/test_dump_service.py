"""A dump streams every record (no per-collection cap) as one valid document."""

from __future__ import annotations

import io

import yaml

from civex.context import AppContext
from civex.services.dump_service import write_dump


def test_dump_writes_every_record_across_pages(
    ctx: AppContext, make_schema, make_collection, project_dir
):
    make_schema("patient", fields=[("name", "string")])
    make_collection("a")
    make_collection("b")
    for i in range(1_100):  # more than two stream pages (500 each)
        ctx.record_svc.add("a", "patient", {"name": f"p{i}"})
    ctx.record_svc.add("b", "patient", {"name": "other"})
    ctx.commit()

    out = io.StringIO()
    counts = write_dump(
        out,
        ctx.schema_svc,
        ctx.dataset_svc,
        ctx.record_svc,
        project_dir / "_civex",
    )

    doc = yaml.safe_load(out.getvalue())
    assert counts.records == len(doc["records"]) == 1_101
    assert {r["dataset"] for r in doc["records"]} == {"a", "b"}
    assert list(doc) == [
        "civex_version",
        "exported_at",
        "schemas",
        "datasets",
        "records",
        "workflows",
        "plugins",
    ]
    assert [s["name"] for s in doc["schemas"]] == ["patient"]


def test_dump_without_data_omits_collections_and_records(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_collection("a")
    make_record("a", "patient", {})

    out = io.StringIO()
    counts = write_dump(
        out, ctx.schema_svc, ctx.dataset_svc, ctx.record_svc, None, include_data=False
    )

    doc = yaml.safe_load(out.getvalue())
    assert doc["datasets"] == [] and doc["records"] == []
    assert counts.records == 0
