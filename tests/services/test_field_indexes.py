"""Field indexes (`IndexService`): which fields get one, keeping the database
in step, and that the explorer's sort and range filter actually use one.

The plan assertions run the statement civex itself sent (captured as it runs)
through `EXPLAIN QUERY PLAN`, so they fail if the compiler and the index ever
stop writing the same expression. No timings: CI machines vary."""

from __future__ import annotations

import pytest
from sqlalchemy import event

from civex.db import field_indexes
from civex.domain.exceptions import ValidationError
from civex.domain.field_index import CHOSEN, UNIQUE_KEY, index_name
from civex.domain.query import RecordQuery


@pytest.fixture()
def study(ctx, make_schema, make_collection):
    make_schema(
        "sample",
        fields=[
            ("code", "string"),
            ("depth", "float"),
            ("taken", "date"),
            ("ok", "boolean"),
            ("photo", "file"),
        ],
    )
    make_collection("study")
    return ctx.schema_svc.get("sample")


def _field(schema, name):
    return next(f for f in schema.fields if f.name == name)


def _fill(ctx, n: int) -> None:
    for i in range(n):
        data = {"code": f"S{i:04d}", "taken": f"2020-01-{i % 28 + 1:02d}"}
        if i % 5:
            data["depth"] = float(i % 97)
        ctx.record_svc.add("study", "sample", data, with_labels=False)
    ctx.commit()


def test_a_chosen_field_and_a_unique_key_are_indexed(ctx, study):
    assert ctx.index_svc.status().fields == []
    ctx.index_svc.set_indexed("sample", "depth", True)
    ctx.schema_svc.set_unique_keys("sample", [["code"]])
    ctx.commit()

    report = ctx.index_svc.status()
    reasons = {s.field_name: s.reasons for s in report.fields}
    assert reasons == {"depth": [CHOSEN], "code": [UNIQUE_KEY]}
    assert [s.built for s in report.missing] == [False, False]

    result = ctx.index_svc.reconcile()
    ctx.commit()
    assert sorted(result.created) == sorted(
        index_name(_field(study, n).id) for n in ("depth", "code")
    )
    assert ctx.index_svc.in_step()
    # The choice is a setting, by field id, never in the database's records.
    assert ctx.config_store.load().db.indexed_fields == [str(_field(study, "depth").id)]


def test_indexes_nothing_wants_any_more_are_dropped(ctx, study, make_schema):
    make_schema("other", fields=[("n", "integer")])
    ctx.index_svc.set_indexed("sample", "depth", True)
    ctx.index_svc.set_indexed("sample", "taken", True)
    ctx.index_svc.set_indexed("other", "n", True)
    ctx.index_svc.reconcile()
    ctx.commit()
    assert len(ctx.index_svc.status().fields) == 3

    ctx.index_svc.set_indexed("sample", "depth", False)  # taken back
    ctx.schema_svc.delete_field("sample", "taken")  # field deleted
    ctx.schema_svc.delete("other")  # schema deleted
    ctx.commit()
    assert len(ctx.index_svc.status().stale) == 3

    result = ctx.index_svc.reconcile()
    ctx.commit()
    assert len(result.dropped) == 3
    assert field_indexes.existing(ctx._session.connection()) == set()


def test_only_single_values_on_the_schema_itself_can_be_indexed(
    ctx, study, make_schema
):
    with pytest.raises(ValidationError):
        ctx.index_svc.set_indexed("sample", "photo", True)
    make_schema("child", fields=[("x", "string")], parent="sample")
    with pytest.raises(ValidationError, match="inherited"):
        ctx.index_svc.set_indexed("child", "code", True)


def _statements(ctx, run):
    """The SELECTs on records that `run()` sends, with their parameters."""
    seen: list[tuple[str, object]] = []
    engine = ctx._session.get_bind()

    def capture(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "FROM records" in statement
        ):
            seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    return seen


def _plan(ctx, statement, parameters) -> str:
    conn = ctx._session.connection()
    rows = conn.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters)
    return "\n".join(str(r[-1]) for r in rows)


def _index_used(ctx, query: RecordQuery, name: str, count: bool = False) -> str:
    def run():
        if count:
            ctx.record_svc.count_records(query)
        else:
            ctx.record_svc.query_records(query, limit=50)

    statement, parameters = _statements(ctx, run)[0]
    plan = _plan(ctx, statement, parameters)
    assert name in plan, plan
    return plan


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sorting_by_an_indexed_field_walks_its_index(ctx, study, direction):
    _fill(ctx, 300)
    ctx.index_svc.set_indexed("sample", "depth", True)
    ctx.index_svc.reconcile()
    ctx.commit()
    name = index_name(_field(study, "depth").id)

    query = RecordQuery(
        dataset="study",
        schema="sample",
        sort=[{"field": "depth", "direction": direction}],
    )
    plan = _index_used(ctx, query, name)
    # The index hands rows over in order: only ties are sorted.
    assert "USE TEMP B-TREE FOR ORDER BY" not in plan

    values = [
        r.data.get("depth") for r in ctx.record_svc.query_records(query, limit=300)
    ]
    present = [v for v in values if v is not None]
    assert present == sorted(present, reverse=direction == "desc")
    assert values[len(present) :] == [None] * (len(values) - len(present))  # nulls last


def test_a_range_filter_counts_through_the_index(ctx, study):
    _fill(ctx, 300)
    ctx.index_svc.set_indexed("sample", "taken", True)
    ctx.index_svc.reconcile()
    ctx.commit()
    name = index_name(_field(study, "taken").id)
    query = RecordQuery(
        dataset="study",
        schema="sample",
        filter_tree={"field": "taken", "op": "gte", "value": "2020-01-27"},
    )
    # The count visits only the matches. (A page in created order may be
    # served by walking `ix_records_live_dataset_created` instead, which the
    # planner prefers when it expects matches to be common.)
    _index_used(ctx, query, name, count=True)
    assert ctx.record_svc.count_records(query) == sum(i % 28 >= 26 for i in range(300))


def test_a_unique_key_check_uses_the_index(ctx, study):
    _fill(ctx, 200)
    ctx.schema_svc.set_unique_keys("sample", [["code"]])
    ctx.index_svc.reconcile()
    ctx.commit()
    name = index_name(_field(study, "code").id)
    statements = _statements(
        ctx,
        lambda: ctx.record_svc.add(
            "study", "sample", {"code": "new"}, with_labels=False
        ),
    )
    plans = [_plan(ctx, s, p) for s, p in statements]
    assert any(name in p for p in plans), plans
