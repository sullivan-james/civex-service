"""What tightening a field's rules does to the records already stored: they
are not re-checked when the rule changes, unlike a uniqueness key, which is
refused while records break it. A stored value the new rule refuses stays as
it is, and an update checks only the values it changes, so the record can
still be edited and its broken values put right one at a time. The data check
(`QualityService`) is what finds them, and the field change says how many."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import ValidationError


@pytest.fixture()
def samples(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("sample", fields=[("code", "string"), ("note", "string")])
    ctx.schema_svc.add_field("sample", "depth", "integer", restrictions={"max": 100})
    ctx.schema_svc.add_field(
        "sample", "status", "string", restrictions={"choices": ["new", "old", "odd"]}
    )
    ctx.schema_svc.add_field(
        "sample", "taken", "date", restrictions={"precision": "year"}
    )
    ctx.commit()
    make_collection("survey")
    return [
        make_record(
            "survey",
            "sample",
            {"code": "a", "depth": 90, "status": "odd", "taken": "2019"},
        ),
        make_record(
            "survey",
            "sample",
            {"code": "b", "depth": 10, "status": "new", "taken": "2019-06-14"},
        ),
    ]


def test_tightening_a_rule_leaves_stored_values_as_they_were(ctx: AppContext, samples):
    ctx.schema_svc.update_field("sample", "depth", restrictions={"max": 50})
    ctx.schema_svc.update_field(
        "sample", "status", restrictions={"choices": ["new", "old"]}
    )
    ctx.schema_svc.update_field("sample", "taken", restrictions={"precision": "day"})
    ctx.commit()  # no error: nothing re-checks the records

    stored = ctx.record_svc.get(str(samples[0].id)).data
    assert (stored["depth"], stored["status"], stored["taken"]) == (90, "odd", "2019")

    # An update checks only the values it changes, so an edit to another
    # field saves, and the old value stays as it was...
    ctx.record_svc.patch(str(samples[0].id), {"note": "seen"})
    assert ctx.record_svc.get(str(samples[0].id)).data["depth"] == 90
    # ...changing a broken value to another broken one is still refused...
    with pytest.raises(ValidationError, match="depth"):
        ctx.record_svc.patch(str(samples[0].id), {"depth": 95})
    # ...and broken values can be put right one at a time.
    ctx.record_svc.patch(str(samples[0].id), {"depth": 40})
    ctx.record_svc.patch(str(samples[0].id), {"status": "old"})
    ctx.record_svc.patch(str(samples[0].id), {"taken": "2019-01-01"})
    stored = ctx.record_svc.get(str(samples[0].id)).data
    assert (stored["depth"], stored["status"], stored["taken"]) == (
        40,
        "old",
        "2019-01-01",
    )


def test_a_new_record_is_checked_in_full(ctx: AppContext, samples, make_record):
    ctx.schema_svc.update_field("sample", "depth", restrictions={"max": 50})
    ctx.commit()
    with pytest.raises(ValidationError, match="depth"):
        make_record("survey", "sample", {"code": "c", "depth": 90})


def test_bulk_edit_fixes_one_of_two_broken_values(ctx: AppContext, samples):
    ctx.schema_svc.update_field("sample", "depth", restrictions={"max": 50})
    ctx.schema_svc.update_field(
        "sample", "status", restrictions={"choices": ["new", "old"]}
    )
    ctx.commit()
    result = ctx.record_svc.bulk_edit({"depth": 40}, ids=[str(samples[0].id)])
    assert result.changed == 1
    stored = ctx.record_svc.get(str(samples[0].id)).data
    assert (stored["depth"], stored["status"]) == (40, "odd")
