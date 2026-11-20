"""Points for a map: the records a query lists, each with its name and the
geometry of a location field (its own, or a record above it's), in a fixed
number of statements however many records."""

from __future__ import annotations

import pytest
from sqlalchemy import event

from civex.context import AppContext
from civex.domain import permissions
from civex.domain.exceptions import NotAllowedError, ValidationError
from civex.domain.query import RecordQuery

POINT = {"type": "Point", "coordinates": [-3.4, 56.1]}
LINE = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
AREA = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("site", fields=[("region", "string"), ("place", "geo")])
    make_schema(
        "sample",
        parent="site",
        fields=[("label", "string"), ("where", "geo"), ("depth", "float")],
    )
    ctx.schema_svc.update("sample", display_template="Sample {label}")
    ctx.commit()
    make_collection("survey")
    north = make_record("survey", "site", {"region": "north", "place": AREA})
    south = make_record("survey", "site", {"region": "south"})
    n, s = str(north.id), str(south.id)
    for parent, data in (
        (n, {"label": "a", "where": POINT, "depth": 1.0}),
        (n, {"label": "b", "where": LINE, "depth": 5.0}),
        (n, {"label": "c", "depth": 9.0}),
        (s, {"label": "d", "where": AREA, "depth": 2.0}),
        (s, {"label": "e", "where": None}),
    ):
        make_record("survey", "sample", data, parent_record_id=parent)
    return {"north": north, "south": south}


def _points(ctx: AppContext, field="where", schema=None, limit=10_000, **query):
    return ctx.record_svc.points(
        RecordQuery(dataset="survey", schema="sample", **query), field, schema, limit
    )


def test_every_kind_of_geometry_with_names(ctx, survey) -> None:
    r = _points(ctx)
    assert (r.schema, r.field, r.total, r.truncated) == ("sample", "where", 3, False)
    got = {p.name: p.geometry for p in r.points}
    # No value and null are left out; lines and areas come as they are.
    assert got == {"Sample a": POINT, "Sample b": LINE, "Sample d": AREA}


def test_the_query_applies(ctx, survey) -> None:
    deep = {"field": "depth", "op": "gte", "value": 2}
    assert {p.name for p in _points(ctx, filter_tree=deep).points} == {
        "Sample b",
        "Sample d",
    }
    assert [p.name for p in _points(ctx, search="d").points] == ["Sample d"]
    inside = _points(ctx, within=str(survey["south"].id))
    assert [p.name for p in inside.points] == ["Sample d"]


def test_a_field_of_a_kind_above(ctx, survey) -> None:
    r = _points(ctx, field="place", schema="site")
    # Each sample under the north site, placed where the site is; the south
    # site has no place.
    assert r.schema == "site" and r.total == 3
    assert {p.name for p in r.points} == {"Sample a", "Sample b", "Sample c"}
    assert all(p.geometry == AREA for p in r.points)
    # Unqualified, the nearest kind that has a field by that name.
    assert _points(ctx, field="place").total == 3


def test_capped(ctx, survey) -> None:
    r = _points(ctx, limit=2)
    assert len(r.points) == 2 and r.total == 3 and r.truncated
    # Oldest first.
    assert [p.name for p in r.points] == ["Sample a", "Sample b"]


def test_refused(ctx, survey) -> None:
    with pytest.raises(ValidationError, match="not a location field"):
        _points(ctx, field="depth")
    with pytest.raises(ValidationError, match="kind of record"):
        ctx.record_svc.points(RecordQuery(dataset="survey"), "where")
    with pytest.raises(ValidationError, match="many of those"):
        ctx.record_svc.points(
            RecordQuery(dataset="survey", schema="site"), "where", "sample"
        )
    with pytest.raises(ValidationError, match="limit"):
        _points(ctx, limit=0)


def test_needs_read(ctx, survey) -> None:
    ctx.record_svc._permissions = permissions.Permissions.nothing()
    with pytest.raises(NotAllowedError):
        _points(ctx)


def test_mapping_costs_the_same_however_many_records(
    ctx: AppContext, survey, make_record
) -> None:
    def statements(field: str, schema: str | None) -> int:
        seen: list[str] = []

        def count(conn, cursor, statement, *args) -> None:
            seen.append(statement)

        engine = ctx._session.get_bind()
        event.listen(engine, "before_cursor_execute", count)
        try:
            _points(ctx, field, schema)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(seen)

    few = statements("where", None), statements("place", "site")
    for i in range(30):
        make_record(
            "survey",
            "sample",
            {"label": f"n{i}", "where": POINT},
            parent_record_id=str(survey["north" if i % 2 else "south"].id),
        )
    assert (statements("where", None), statements("place", "site")) == few
