"""PostgreSQL: field indexes are built (CONCURRENTLY) and used, and an
equality filter written as JSONB containment (which the GIN index
`ix_records_data_gin` answers) finds exactly the records the typed comparison
does.

Runs only when CIVEX_TEST_POSTGRES_URL names a server it may create databases
on; each test makes a database of its own. The SQLite side is
tests/services/test_field_indexes.py."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from civex.config import load_config
from civex.context import build_local_context
from civex.db.models import Record
from civex.domain.field_index import index_name
from civex.domain.filters import parse_filter_tree
from civex.domain.query import RecordQuery
from civex.project import scaffold_project
from civex.repositories.local import record_repo

_SERVER = os.environ.get("CIVEX_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not _SERVER, reason="CIVEX_TEST_POSTGRES_URL not set")


@pytest.fixture()
def pg(tmp_path):
    name = f"civex_{uuid.uuid4().hex[:12]}"
    admin = create_engine(_SERVER, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(_SERVER).set(database=name).render_as_string(hide_password=False)
    root = tmp_path / "pg"
    scaffold_project(root, db_url=url)
    previous = os.getcwd()
    os.chdir(root)
    try:
        ctx = build_local_context(load_config())
        yield ctx
    finally:
        os.chdir(previous)
    ctx.close()
    ctx._session.get_bind().dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def _study(ctx, n: int):
    ctx.schema_svc.create("sample")
    for name, dtype in [
        ("code", "string"),
        ("depth", "float"),
        ("count", "integer"),
        ("ok", "boolean"),
        ("taken", "date"),
        ("kind", "enum"),
    ]:
        ctx.schema_svc.add_field("sample", name, dtype)
    ctx.dataset_svc.create("study")
    ctx.commit()
    rows = []
    for i in range(n):
        data: dict = {"code": f"S{i % 50:03d}", "taken": f"2020-01-{i % 28 + 1:02d}"}
        if i % 5:
            data["depth"] = [1, 1.0, 2.5, 30, 0.1][i % 5]
        if i % 7:
            data["count"] = i % 11
        if i % 3:
            data["ok"] = bool(i % 2)
        rows.append(data)
    for data in rows:
        ctx.record_svc.add("study", "sample", data, with_labels=False)
    ctx.commit()
    return ctx.schema_svc.get("sample")


TREES = [
    {"field": "depth", "op": "eq", "value": 1},
    {"field": "depth", "op": "eq", "value": 1.0},
    {"field": "depth", "op": "eq", "value": 0.1},
    {"field": "depth", "op": "in", "value": [30, 2.5]},
    {"field": "count", "op": "eq", "value": 3},
    {"field": "count", "op": "eq", "value": 3.0},
    {"field": "count", "op": "eq", "value": "3"},  # text: left to the comparison
    {"field": "ok", "op": "eq", "value": True},
    {"field": "ok", "op": "eq", "value": False},
    {"field": "code", "op": "eq", "value": "S007"},
    {"field": "code", "op": "in", "value": ["S001", "S002", "nope"]},
    {"field": "taken", "op": "eq", "value": "2020-01-05"},
    {"field": "code", "op": "eq", "value": "it's"},
]


def _ids(ctx, schema, tree, pg: bool) -> set:
    fields = {f.name: f for f in schema.fields}

    def resolve(node):
        f = fields[node.field]
        node.field, node.dtype = str(f.id), f.dtype
        return node

    from civex.domain.filters import map_leaves

    node = map_leaves(parse_filter_tree(tree), resolve)
    condition = record_repo._build_filter_condition(node, pg)
    rows = ctx._session.execute(
        select(Record.id).where(Record.deleted_at.is_(None), condition)
    )
    return {r[0] for r in rows}


def test_containment_matches_what_the_comparison_matches(pg):
    schema = _study(pg, 300)
    for tree in TREES:
        assert _ids(pg, schema, tree, pg=True) == _ids(pg, schema, tree, pg=False), tree
    # And the service's own path agrees with the counts.
    q = RecordQuery(
        dataset="study",
        schema="sample",
        filter_tree={"field": "depth", "op": "eq", "value": 1},
    )
    assert pg.record_svc.count_records(q) == len(_ids(pg, schema, TREES[0], pg=False))


def _plan(ctx, run) -> str:
    from sqlalchemy import event

    seen = []
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
    statement, parameters = seen[0]
    conn = ctx._session.connection().connection.dbapi_connection
    cur = conn.cursor()
    cur.execute("EXPLAIN " + statement, parameters)
    return "\n".join(r[0] for r in cur.fetchall())


def test_an_equality_filter_uses_the_gin_index(pg):
    schema = _study(pg, 300)
    code = next(f for f in schema.fields if f.name == "code")
    # Enough other records that a selective containment is worth an index.
    pg._session.execute(
        text(
            "INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at) "
            "SELECT gen_random_uuid(), r.dataset_id, r.schema_id, "
            "jsonb_build_object(:code, 'X' || g), now(), now() "
            "FROM generate_series(1, 20000) g, "
            "(SELECT dataset_id, schema_id FROM records LIMIT 1) r"
        ),
        {"code": str(code.id)},
    )
    pg.commit()
    pg._session.execute(text("ANALYZE records"))
    pg._session.execute(text("SET enable_seqscan = off"))
    q = RecordQuery(
        dataset="study",
        schema="sample",
        filter_tree={"field": "code", "op": "eq", "value": "S007"},
    )
    plan = _plan(pg, lambda: pg.record_svc.count_records(q))
    assert "ix_records_data_gin" in plan, plan


def test_a_field_index_is_built_and_serves_a_sort_and_a_range(pg):
    schema = _study(pg, 2000)
    pg.index_svc.set_indexed("sample", "depth", True)
    pg.index_svc.set_indexed("sample", "taken", True)
    pg.commit()
    result = pg.index_svc.reconcile()
    pg.commit()
    depth = next(f for f in schema.fields if f.name == "depth")
    taken = next(f for f in schema.fields if f.name == "taken")
    assert set(result.created) == {index_name(depth.id), index_name(taken.id)}
    assert pg.index_svc.in_step()

    sort = RecordQuery(dataset="study", schema="sample", sort=[{"field": "depth"}])
    plan = _plan(pg, lambda: pg.record_svc.query_records(sort, limit=50))
    assert index_name(depth.id) in plan, plan

    pg._session.execute(text("SET enable_seqscan = off"))
    rng = RecordQuery(
        dataset="study",
        schema="sample",
        filter_tree={"field": "taken", "op": "gte", "value": "2020-01-27"},
    )
    plan = _plan(pg, lambda: pg.record_svc.count_records(rng))
    assert index_name(taken.id) in plan, plan
    pg._session.rollback()

    pg.index_svc.set_indexed("sample", "depth", False)
    pg.commit()
    assert pg.index_svc.reconcile().dropped == [index_name(depth.id)]
