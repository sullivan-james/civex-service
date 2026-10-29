"""`field=value` filters name a schema's fields, so they need the schema: without
one a filter once quietly matched nothing."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import ValidationError
from civex.domain.query import RecordQuery


def test_a_field_filter_without_a_schema_is_refused(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("sample", fields=[("site", "string")])
    make_collection("survey")
    ctx.record_svc.add("survey", "sample", {"site": "A3"})

    with pytest.raises(ValidationError, match="choose a schema"):
        ctx.record_svc.find("survey", filters=["site=A3"])
    with pytest.raises(ValidationError, match="choose a schema"):
        ctx.record_svc.resolve(RecordQuery(dataset="survey", where=["site=A3"]))

    found = ctx.record_svc.find("survey", schema_name="sample", filters=["site=A3"])
    assert [r.data["site"] for r in found] == ["A3"]
