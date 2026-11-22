"""Summaries: records grouped by field values, measures over each group, over
exactly what a query lists, in one SQL statement."""

from __future__ import annotations

import pytest
from sqlalchemy import event

from civex.context import AppContext
from civex.domain import permissions
from civex.domain.exceptions import NotAllowedError, ValidationError
from civex.domain.query import RecordQuery
from civex.domain.summary import GroupBy, Measure, SummaryRequest


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("site", fields=[("region", "string"), ("elevation", "integer")])
    make_schema(
        "sample",
        parent="site",
        fields=[
            ("label", "string"),
            ("depth", "float"),
            ("count", "integer"),
            ("taken", "date"),
            ("seen", "datetime"),
            ("tags", "tags"),
            ("checked", "boolean"),
            ("where", "geo"),
            ("site_ref", "reference"),
        ],
    )
    ctx.schema_svc.update_field("sample", "depth", restrictions={"unit": "m"})
    ctx.schema_svc.update_field("sample", "taken", restrictions={"precision": "year"})
    ctx.commit()
    make_collection("survey")
    north = make_record("survey", "site", {"region": "north", "elevation": 10})
    south = make_record("survey", "site", {"region": "south", "elevation": 30})
    n, s = str(north.id), str(south.id)
    rows = [
        (n, {"label": "a", "depth": 1.0, "count": 1, "taken": "2019-06-14",
             "tags": ["x", "y"], "checked": True, "site_ref": s,
             "seen": "2024-03-31T00:30:00+00:00"}),
        (n, {"label": "b", "depth": 3.0, "count": 2, "taken": "2019-06",
             "tags": ["x"], "checked": False,
             "seen": "2024-03-31T01:30:00+00:00"}),
        (n, {"label": "c", "depth": 12.0, "count": 3, "taken": "2019",
             "where": {"type": "Point", "coordinates": [1, 2]}}),
        (s, {"label": "d", "depth": 7.5, "count": 4, "taken": "2020-01-02",
             "tags": []}),
        (s, {"label": "e", "taken": "2020-01-05"}),
    ]  # fmt: skip
    for parent, data in rows:
        make_record("survey", "sample", data, parent_record_id=parent)
    return {"north": north, "south": south}


def _run(ctx: AppContext, *, by=(), measures=("count",), **query):
    request = SummaryRequest(
        group_by=[g if isinstance(g, GroupBy) else GroupBy(g) for g in by],
        measures=[
            m
            if isinstance(m, Measure)
            else Measure(*m.split(":", 1))
            if ":" in m
            else Measure(m)
            for m in measures
        ],
    )
    return ctx.record_svc.summarise(
        RecordQuery(dataset="survey", schema="sample", **query), request
    )


def _table(result):
    return {tuple(g.value for g in row.groups): row.values for row in result.rows}


def test_every_measure_over_every_record(ctx, survey) -> None:
    r = _run(
        ctx,
        measures=[
            "count",
            "filled:depth",
            "distinct:label",
            "min:depth",
            "max:depth",
            "mean:depth",
            "sum:count",
            "min:taken",
            "max:taken",
            "filled:where",
            "filled:tags",
        ],
    )
    assert r.rows == []
    assert r.total == [5, 4, 5, 1.0, 12.0, 5.875, 10, "2019", "2020-01-05", 1, 2]
    # A value of the field carries its unit; a count doesn't.
    units = {c.key: c.unit for c in r.measure_columns}
    assert units["mean:depth"] == "m" and units["filled:depth"] is None
    assert isinstance(r.total[6], int)


def test_group_by_value_with_blanks_last(ctx, survey) -> None:
    r = _run(ctx, by=["checked"], measures=["count", "mean:depth"])
    assert [(g.groups[0].label, g.values) for g in r.rows] == [
        ("No", [1, 3.0]),
        ("Yes", [1, 1.0]),
        ("No value", [3, (12.0 + 7.5) / 2]),
    ]
    assert r.total == [5, 5.875]


def test_numbers_into_ranges(ctx, survey) -> None:
    r = _run(ctx, by=[GroupBy("depth", bin=5)])
    rows = [(g.groups[0].lower, g.groups[0].upper, g.values[0]) for g in r.rows]
    assert rows == [(0, 5, 2), (5, 10, 1), (10, 15, 1), (None, None, 1)]
    assert r.rows[0].groups[0].label == "0 to under 5 m"
    # Its condition lists exactly its records.
    where = r.rows[0].where
    assert where == {
        "and": [
            {"field": "depth", "schema": "sample", "op": "gte", "value": 0},
            {"field": "depth", "schema": "sample", "op": "lt", "value": 5},
        ]
    }
    listed = ctx.record_svc.count_records(
        RecordQuery(dataset="survey", schema="sample", filter_tree=where)
    )
    assert listed == 2


def test_partial_dates_keep_their_own_group(ctx, survey) -> None:
    r = _run(ctx, by=[GroupBy("taken", bucket="month")])
    groups = [(g.groups[0].value, g.groups[0].precision, g.values[0]) for g in r.rows]
    assert groups == [
        ("2019", "year", 1),  # only the year is known
        ("2019-06", None, 2),
        ("2020-01", None, 2),
    ]
    assert r.rows[0].groups[0].label == "2019, month not known"
    for row in r.rows:
        n = ctx.record_svc.count_records(
            RecordQuery(dataset="survey", schema="sample", filter_tree=row.where)
        )
        assert n == row.values[0], row.groups[0].label
    by_year = _table(_run(ctx, by=[GroupBy("taken", bucket="year")]))
    assert by_year == {("2019",): [3], ("2020",): [2]}
    by_week = _run(ctx, by=[GroupBy("taken", bucket="week")])
    assert [(g.groups[0].value, g.values[0]) for g in by_week.rows] == [
        ("2019", 1),
        ("2019-06", 1),
        ("2019-06-10", 1),  # the Monday of 14 June 2019
        ("2019-12-30", 2),  # 2 and 5 January 2020 share a week
    ]


def test_datetimes_group_in_the_zone(ctx, survey) -> None:
    # 00:30 and 01:30 UTC on 31 March 2024 are the evening before in Los
    # Angeles (-7).
    utc = _table(_run(ctx, by=[GroupBy("seen", bucket="day")]))
    assert utc == {("2024-03-31",): [2], (None,): [3]}
    ctx.dataset_svc.update("survey", timezone="America/Los_Angeles")
    ctx.commit()
    r = _run(ctx, by=[GroupBy("seen", bucket="day")])
    assert r.timezone == "America/Los_Angeles"
    assert _table(r) == {("2024-03-30",): [2], (None,): [3]}
    assert (r.rows[0].groups[0].lower, r.rows[0].groups[0].upper) == (
        "2024-03-30",
        "2024-03-31",
    )
    # Its condition is in stored UTC, and lists exactly its records.
    assert r.rows[0].where["and"][0]["value"] == "2024-03-30T07:00:00+00:00"
    n = ctx.record_svc.count_records(
        RecordQuery(dataset="survey", schema="sample", filter_tree=r.rows[0].where)
    )
    assert n == 2
    # The field's own zone wins over the collection's.
    ctx.schema_svc.update_field(
        "sample", "seen", restrictions={"timezone": "Asia/Tokyo"}
    )
    ctx.commit()
    assert _table(_run(ctx, by=[GroupBy("seen", bucket="day")])) == {
        ("2024-03-31",): [2],
        (None,): [3],
    }


def test_datetimes_across_a_clock_change(ctx, survey, make_record) -> None:
    # London is UTC+1 until 01:00 UTC on 27 October 2024, then UTC+0: both
    # of these are 27 October there, though a day apart in UTC.
    for at in ("2024-10-26T23:30:00+00:00", "2024-10-27T23:30:00+00:00"):
        make_record(
            "survey",
            "sample",
            {"label": at, "seen": at},
            parent_record_id=str(survey["north"].id),
        )
    query = RecordQuery(
        dataset="survey",
        schema="sample",
        filter_tree={"field": "seen", "op": "gte", "value": "2024-10"},
    )
    by_day = SummaryRequest([GroupBy("seen", bucket="day")])
    assert _table(ctx.record_svc.summarise(query, by_day)) == {
        ("2024-10-26",): [1],
        ("2024-10-27",): [1],
    }
    ctx.dataset_svc.update("survey", timezone="Europe/London")
    ctx.commit()
    assert _table(ctx.record_svc.summarise(query, by_day)) == {("2024-10-27",): [2]}
    by_week = SummaryRequest([GroupBy("seen", bucket="week")])
    assert _table(ctx.record_svc.summarise(query, by_week)) == {("2024-10-21",): [2]}


def test_a_list_groups_by_each_item(ctx, survey) -> None:
    r = _run(ctx, by=["tags"])
    assert _table(r) == {("x",): [2], ("y",): [1], (None,): [3]}
    assert all(row.where is None for row in r.rows)
    assert r.total == [5]  # each record once


def test_group_by_a_field_of_the_kind_above(ctx, survey) -> None:
    r = _run(
        ctx,
        by=[GroupBy("region", schema="site")],
        measures=["count", "mean:depth"],
    )
    assert _table(r) == {("north",): [3, 16 / 3], ("south",): [2, 7.5]}
    assert r.group_columns[0].label == "Site Region"
    # An inherited name means the record above's field, like a filter's.
    assert _table(_run(ctx, by=["region"])) == {("north",): [3], ("south",): [2]}
    where = r.rows[0].where
    assert where == {"field": "region", "schema": "site", "op": "eq", "value": "north"}
    assert (
        ctx.record_svc.count_records(
            RecordQuery(dataset="survey", schema="sample", filter_tree=where)
        )
        == 3
    )


def test_several_groupings(ctx, survey) -> None:
    r = _run(ctx, by=[GroupBy("region", schema="site"), "checked"])
    assert _table(r) == {
        ("north", False): [1],
        ("north", True): [1],
        ("north", None): [1],
        ("south", None): [2],
    }


def test_a_link_is_named(ctx, survey) -> None:
    r = _run(ctx, by=["site_ref"])
    assert [g.groups[0].label for g in r.rows] == ["south", "No value"]


def test_the_query_is_applied(ctx, survey) -> None:
    r = _run(
        ctx,
        measures=["count"],
        filter_tree={"field": "depth", "op": "gte", "value": 3},
    )
    assert r.total == [3]
    assert _run(ctx, search="d").total == [1]
    assert _run(ctx, within=str(survey["south"].id)).total == [2]


def test_bad_legacy_values_are_not_numbers(ctx, survey, make_record) -> None:
    rec = make_record(
        "survey", "sample", {"label": "f"}, parent_record_id=str(survey["north"].id)
    )
    # A value written before the field's type changed: stored as text.
    from civex.db.models import Record

    row = ctx._session.get(Record, rec.id)
    depth = str(ctx.schema_svc.get("sample").fields[1].id)
    row.data = {**row.data, depth: "deep"}
    ctx.commit()
    r = _run(ctx, measures=["count", "filled:depth", "mean:depth", "max:depth"])
    # Still a value (filled), just not a number.
    assert r.total == [6, 5, 5.875, 12.0]


def test_what_a_field_allows(ctx, survey) -> None:
    with pytest.raises(ValidationError, match="mean"):
        _run(ctx, measures=["mean:label"])
    with pytest.raises(ValidationError, match="group by 'where'"):
        _run(ctx, by=["where"])
    with pytest.raises(ValidationError, match="not a date"):
        _run(ctx, by=[GroupBy("depth", bucket="month")])
    with pytest.raises(ValidationError, match="not a number"):
        _run(ctx, by=[GroupBy("label", bin=2)])
    with pytest.raises(ValidationError, match="kind of record"):
        ctx.record_svc.summarise(RecordQuery(dataset="survey"), SummaryRequest())


def test_too_many_groups_is_truncated(ctx, survey) -> None:
    r = ctx.record_svc.summarise(
        RecordQuery(dataset="survey", schema="sample"),
        SummaryRequest([GroupBy("label")], limit=2),
    )
    assert r.truncated and len(r.rows) == 2 and r.total == [5]


def test_needs_read(ctx, survey) -> None:
    ctx.record_svc._permissions = permissions.Permissions.nothing()
    with pytest.raises(NotAllowedError):
        _run(ctx)


def test_one_statement_however_many_records(
    ctx: AppContext, survey, make_record
) -> None:
    request = SummaryRequest(
        [GroupBy("region", schema="site"), GroupBy("taken", bucket="month")],
        [Measure("count"), Measure("mean", "depth"), Measure("distinct", "label")],
    )
    query = RecordQuery(dataset="survey", schema="sample")

    def statements() -> tuple[int, int]:
        seen: list[str] = []

        def count(conn, cursor, statement, *args) -> None:
            seen.append(statement)

        engine = ctx._session.get_bind()
        event.listen(engine, "before_cursor_execute", count)
        try:
            ctx.record_svc.summarise(query, request)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(seen), len([s for s in seen if "GROUP BY" in s])

    few = statements()
    for i in range(30):
        make_record(
            "survey",
            "sample",
            {"label": f"n{i}", "depth": i, "taken": f"2021-0{1 + i % 9}"},
            parent_record_id=str(survey["north"].id),
        )
    assert statements() == few
    assert few[1] == 1  # the summary itself is one statement


# --- how many records of a kind beneath sit inside them


def test_counting_the_records_inside_each_group(
    ctx: AppContext, survey, make_schema, make_record
) -> None:
    make_schema("reading", parent="sample", fields=[("value", "float")])
    ctx.commit()
    samples = ctx.record_svc.query_records(
        RecordQuery(dataset="survey", schema="sample"), limit=10
    )
    by_label = {s.data["label"]: str(s.id) for s in samples}
    for label, n in (("a", 2), ("d", 3)):
        for i in range(n):
            make_record(
                "survey", "reading", {"value": i}, parent_record_id=by_label[label]
            )
    gone = make_record(
        "survey", "reading", {"value": 9}, parent_record_id=by_label["a"]
    )
    ctx.record_svc.delete(str(gone.id))
    ctx.commit()

    result = ctx.record_svc.summarise(
        RecordQuery(dataset="survey", schema="site"),
        SummaryRequest(
            [GroupBy("region")],
            [
                Measure("count"),
                Measure("inside", "sample"),
                Measure("inside", "reading"),
            ],
        ),
    )
    assert [c.label for c in result.measure_columns] == [
        "Records",
        "Sample inside",
        "Reading inside",
    ]
    assert [(r.groups[0].value, r.values) for r in result.rows] == [
        ("north", [1, 3, 2]),
        ("south", [1, 2, 3]),
    ]
    assert result.total == [2, 5, 5]
    # The list's own filter still decides which records are counted inside.
    one = ctx.record_svc.summarise(
        RecordQuery(
            dataset="survey",
            schema="site",
            filter_tree={"field": "region", "op": "eq", "value": "south"},
        ),
        SummaryRequest([], [Measure("inside", "reading")]),
    )
    assert one.total == [3]


def test_inside_names_a_kind_beneath(ctx: AppContext, survey) -> None:
    for measure in (Measure("inside", "site"), Measure("inside", "nothing")):
        with pytest.raises(ValidationError, match="beneath"):
            ctx.record_svc.summarise(
                RecordQuery(dataset="survey", schema="sample"),
                SummaryRequest([], [measure]),
            )
    with pytest.raises(ValidationError, match="beneath"):
        SummaryRequest([], [Measure("inside")]).check()


def test_counting_inside_is_one_statement_however_many_records(
    ctx: AppContext, survey, make_record
) -> None:
    request = SummaryRequest(
        [GroupBy("region")], [Measure("count"), Measure("inside", "sample")]
    )
    query = RecordQuery(dataset="survey", schema="site")

    def statements() -> int:
        seen: list[str] = []

        def count(conn, cursor, statement, *args) -> None:
            seen.append(statement)

        engine = ctx._session.get_bind()
        event.listen(engine, "before_cursor_execute", count)
        try:
            ctx.record_svc.summarise(query, request)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(seen)

    few = statements()
    for i in range(20):
        site = make_record("survey", "site", {"region": f"r{i}"})
        for _ in range(3):
            make_record("survey", "sample", {}, parent_record_id=str(site.id))
    ctx.commit()
    assert statements() == few
