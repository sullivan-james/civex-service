"""What tightening a field's rules does to the records already stored: they
are not re-checked when the rule changes, unlike a uniqueness key, which is
refused while records break it. A stored value the new rule refuses stays as
it is, and the record can't then be saved at all (an edit checks every value,
not only the changed ones) until that value is put right. The data check
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

    # An edit checks every value, so even a change to another field is
    # refused, naming the value that no longer passes...
    with pytest.raises(ValidationError, match="depth"):
        ctx.record_svc.patch(str(samples[0].id), {"note": "seen"})
    # ...and putting one value right isn't enough while another breaks too.
    with pytest.raises(ValidationError, match="status"):
        ctx.record_svc.patch(str(samples[0].id), {"depth": 40})
    ctx.record_svc.patch(
        str(samples[0].id), {"depth": 40, "status": "old", "taken": "2019-01-01"}
    )
    ctx.record_svc.patch(str(samples[0].id), {"note": "seen"})
