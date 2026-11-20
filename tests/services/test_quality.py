"""Data checks: what in the records a query lists needs a look, per kind and
field, found by the rules that already exist (restrictions, uniqueness keys,
where a reference may point, where a file is) and never by copies of them."""

from __future__ import annotations

import uuid

import pytest

from civex.context import AppContext
from civex.domain import quality
from civex.domain.exceptions import NotAllowedError, NotFoundError, ValidationError
from civex.domain.permissions import Permissions
from civex.domain.query import RecordQuery


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("site", fields=[("name", "string")])
    make_schema("sample", fields=[("code", "string")], parent="site")
    ctx.schema_svc.add_field("sample", "depth", "integer", restrictions={"max": 100})
    ctx.schema_svc.add_field(
        "sample", "status", "string", restrictions={"choices": ["new", "old"]}
    )
    ctx.schema_svc.add_field("sample", "site_ref", "reference")
    ctx.schema_svc.add_field("sample", "sound", "file")
    ctx.schema_svc.update_field("sample", "code", required=True)
    ctx.commit()
    make_collection("survey")
    site = make_record("survey", "site", {"name": "a"})
    samples = [
        make_record(
            "survey",
            "sample",
            {"code": f"s{i}", "depth": 10 * i, "status": "new"},
            parent_record_id=str(site.id),
        )
        for i in range(6)
    ]
    return site, samples


def _q(schema: str = "sample") -> RecordQuery:
    return RecordQuery(dataset="survey", schema=schema)


def _kind(report: quality.QualityReport, schema: str) -> quality.KindReport:
    return next(k for k in report.kinds if k.schema == schema)


def _line(kind: quality.KindReport, issue: str, field: str) -> quality.IssueCount:
    return next(i for i in kind.issues if i.issue == issue and i.field == field)


def test_clean_records_have_nothing_to_report(ctx: AppContext, survey):
    report = ctx.quality_svc.check(_q())
    kind = _kind(report, "sample")
    assert (kind.records, kind.records_with_issues, kind.issues) == (6, 0, [])
    # Blanks are counted for every field, as information.
    blanks = {b.field: b.blank for b in kind.blanks}
    assert blanks["code"] == 0 and blanks["sound"] == 6


def test_a_tightened_rule_shows_the_values_it_now_refuses(ctx: AppContext, survey):
    ctx.schema_svc.update_field("sample", "depth", restrictions={"max": 25})
    ctx.schema_svc.update_field("sample", "status", restrictions={"choices": ["old"]})
    ctx.commit()
    kind = _kind(ctx.quality_svc.check(_q()), "sample")
    depth = _line(kind, quality.BREAKS_RULE, "depth")
    assert depth.count == 3  # 30, 40, 50
    assert len(depth.examples) == 3
    assert "exceeds maximum (25)" in depth.examples[0].message
    assert depth.examples[0].record_name
    status = _line(kind, quality.BREAKS_RULE, "status")
    assert status.count == 6
    assert len(status.examples) == quality.MAX_EXAMPLES  # the count stays exact
    assert kind.records_with_issues == 6


def test_a_required_field_left_empty_is_an_issue_other_blanks_are_counts(
    ctx: AppContext, survey
):
    _, samples = survey
    # A required field is asked for only when a record is made (and not for
    # one made before it was required): written past the service here.
    ctx.record_svc.records_repo.update(id=samples[0].id, data={})
    ctx.commit()
    kind = _kind(ctx.quality_svc.check(_q()), "sample")
    blank = _line(kind, quality.BLANK, "code")
    assert blank.count == 1
    assert blank.filter == {
        "or": [
            {"field": "code", "op": "is_null", "schema": "sample"},
            {"field": "code", "op": "eq", "value": "", "schema": "sample"},
        ]
    }
    # Its filter lists exactly that record.
    listed = ctx.record_svc.query_records(
        RecordQuery(dataset="survey", schema="sample", filter_tree=blank.filter)
    )
    assert [r.id for r in listed] == [samples[0].id]
    # Not required: counted, not an issue.
    assert not [i for i in kind.issues if i.field == "sound"]


def test_records_sharing_a_unique_key(ctx: AppContext, survey, make_record):
    site, samples = survey
    ctx.schema_svc.set_unique_keys("sample", [["code"]])
    ctx.commit()
    # A duplicate can only come from before the key, or from elsewhere (sync):
    # written past the service here.
    ctx.record_svc.records_repo.update(
        id=samples[1].id,
        data={
            **ctx.record_svc.records_repo.get_by_prefix(str(samples[1].id)).data,
            ctx.schema_svc.name_to_id_map(ctx.schema_svc.get("sample"))["code"]: "s0",
        },
    )
    ctx.commit()
    kind = _kind(ctx.quality_svc.check(_q()), "sample")
    line = _line(kind, quality.DUPLICATE_KEY, "code")
    assert line.count == 2
    assert {e.record_id for e in line.examples} == {
        str(samples[0].id),
        str(samples[1].id),
    }


def test_a_link_to_a_record_that_is_gone(ctx: AppContext, survey):
    site, samples = survey
    ctx.record_svc.patch(str(samples[0].id), {"site_ref": str(site.id)})
    ctx.commit()
    ids = ctx.schema_svc.name_to_id_map(ctx.schema_svc.get("sample"))
    raw = ctx.record_svc.records_repo.get_by_prefix(str(samples[1].id))
    ctx.record_svc.records_repo.update(
        id=raw.id, data={**raw.data, ids["site_ref"]: str(uuid.uuid4())}
    )
    ctx.commit()
    kind = _kind(ctx.quality_svc.check(_q()), "sample")
    line = _line(kind, quality.BROKEN_REFERENCE, "site_ref")
    assert line.count == 1
    assert line.examples[0].record_id == str(samples[1].id)
    assert "not found" in line.examples[0].message


def test_a_file_that_is_nowhere(ctx: AppContext, survey):
    _, samples = survey
    ids = ctx.schema_svc.name_to_id_map(ctx.schema_svc.get("sample"))
    raw = ctx.record_svc.records_repo.get_by_prefix(str(samples[2].id))
    ctx.record_svc.records_repo.update(
        id=raw.id,
        data={
            **raw.data,
            ids["sound"]: {"sha256": "ab" * 32, "filename": "lost.wav", "size": 3},
        },
    )
    ctx.commit()
    kind = _kind(ctx.quality_svc.check(_q()), "sample")
    line = _line(kind, quality.MISSING_FILE, "sound")
    assert line.count == 1
    assert "lost.wav" in line.examples[0].message


def test_a_stored_file_is_not_missing(ctx: AppContext, survey, tmp_path):
    _, samples = survey
    path = tmp_path / "a.wav"
    path.write_bytes(b"abc")
    ref = ctx.file_svc.store(path)
    ctx.record_svc.patch(str(samples[3].id), {"sound": ref.to_dict()})
    ctx.commit()
    kind = _kind(ctx.quality_svc.check(_q()), "sample")
    assert not [i for i in kind.issues if i.issue == quality.MISSING_FILE]


def test_the_records_with_an_issue_are_listed_a_page_at_a_time(ctx: AppContext, survey):
    _, samples = survey
    ctx.schema_svc.update_field("sample", "depth", restrictions={"max": 15})
    ctx.commit()
    found, total = ctx.quality_svc.records_with(
        _q(), quality.BREAKS_RULE, field="depth", limit=2, offset=1
    )
    assert total == 4
    assert [f.record_id for f in found] == [str(s.id) for s in samples[3:5]]
    with pytest.raises(ValidationError):
        ctx.quality_svc.records_with(_q(), "odd")
    # The ids are what a bulk edit takes, so the explorer can put them right.
    every, _ = ctx.quality_svc.records_with(_q(), quality.BREAKS_RULE, field="depth")
    ctx.record_svc.bulk_edit({"depth": 15}, ids=[f.record_id for f in every])
    ctx.commit()
    assert ctx.quality_svc.records_with(_q(), quality.BREAKS_RULE)[1] == 0


def test_a_query_narrows_the_check(ctx: AppContext, survey):
    ctx.schema_svc.update_field("sample", "depth", restrictions={"max": 25})
    ctx.commit()
    query = RecordQuery(
        dataset="survey",
        schema="sample",
        filter_tree={"field": "depth", "op": "gte", "value": 40},
    )
    kind = _kind(ctx.quality_svc.check(query), "sample")
    assert kind.records == 2
    assert _line(kind, quality.BREAKS_RULE, "depth").count == 2


def test_without_a_kind_every_kind_is_checked(ctx: AppContext, survey):
    report = ctx.quality_svc.check(RecordQuery(dataset="survey"))
    assert {k.schema for k in report.kinds} == {"site", "sample"}
    assert report.records == 7


def test_checking_a_field_before_changing_it(ctx: AppContext, survey):
    check = ctx.quality_svc.check_field("sample", "depth", restrictions={"max": 25})
    assert (check.breaks_rule, check.blank) == (3, 0)
    assert len(check.examples) == 3
    # Nothing changed.
    assert ctx.schema_svc.get("sample").fields[1].restrictions == {"max": 100}
    # As the rules are now: nothing.
    assert ctx.quality_svc.check_field("sample", "depth").breaks_rule == 0
    # Making a field required counts the records that leave it empty.
    assert ctx.quality_svc.check_field("sample", "sound", required=True).blank == 6
    with pytest.raises(ValidationError):
        ctx.quality_svc.check_field("sample", "depth", restrictions={"choices": [1]})
    with pytest.raises(NotFoundError):
        ctx.quality_svc.check_field("sample", "name")  # the site's field


def test_reading_is_asked(ctx: AppContext, survey):
    ctx.quality_svc._permissions = Permissions.nothing()
    with pytest.raises(NotAllowedError):
        ctx.quality_svc.check(_q())


def _queries(ctx: AppContext, fn) -> int:
    from sqlalchemy import event

    count = {"n": 0}
    engine = ctx._session.get_bind()

    def bump(*_args, **_kwargs):
        count["n"] += 1

    event.listen(engine, "before_cursor_execute", bump)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", bump)
    return count["n"]


def test_a_check_costs_the_same_however_many_records(
    ctx: AppContext, make_schema, make_collection, make_record
):
    """Every value is checked, but the database is asked a fixed number of
    times per page: the page itself, its references together, each key once."""
    make_schema("target", fields=[("name", "string")])
    make_schema("trial", fields=[("subject", "string")])
    ctx.schema_svc.add_field("trial", "depth", "integer")
    ctx.schema_svc.add_field("trial", "target", "reference")
    ctx.schema_svc.set_unique_keys("trial", [["subject"]])
    ctx.commit()
    make_collection("study")

    def check(n: int, tag: str) -> int:
        ctx.schema_svc.update_field("trial", "depth", restrictions={})
        make_collection(tag)
        target = make_record(tag, "target", {"name": "t"})
        for i in range(n):
            make_record(
                tag, "trial", {"subject": f"t{i}", "depth": i, "target": str(target.id)}
            )
        # Half of them now break the rule.
        ctx.schema_svc.update_field("trial", "depth", restrictions={"max": n // 2})
        ctx.commit()
        return _queries(
            ctx, lambda: ctx.quality_svc.check(RecordQuery(dataset=tag, schema="trial"))
        )

    small, big = check(3, "small"), check(30, "big")
    assert small == big <= 15, (small, big)
