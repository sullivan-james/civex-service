"""`Project.read_engine`: reads that are replica-safe by design are served by a
second (replica) engine; everything else, and any request that must see its own
writes, uses the primary.

PostgreSQL tests need CIVEX_TEST_POSTGRES_URL (a scratch database); each makes
its own schema and opens two engines on it labelled by `application_name`, so
the tests can tell which engine ran a statement. The "replica" is the same
database: what is tested is the routing, which is all civex owns.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError

from civex.config import FileConfigStore, load_config_at
from civex.context import build_context
from civex.db.migrate import ensure_schema_current
from civex.project import Project, scaffold_project
from civex.server.app import create_app

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")
needs_pg = pytest.mark.skipif(
    not _PG_URL, reason="set CIVEX_TEST_POSTGRES_URL to a scratch PostgreSQL DB"
)
_WRITES = {"INSERT", "UPDATE", "DELETE"}


def test_sqlite_ignores_a_read_engine(tmp_path: Path):
    """On SQLite a read engine is never used, even when one is given."""
    scaffold_project(tmp_path / "p")
    config = load_config_at(tmp_path / "p")
    other = create_engine(f"sqlite:///{tmp_path / 'other.db'}")
    project = Project(
        config=config,
        config_store=FileConfigStore(config.project_root),
        read_engine=other,
    )
    ctx = build_context(project, read_only=True)
    try:
        assert ctx.on_read_engine is False
        ctx.schema_svc.create("thing")  # writes work: this is the primary
        ctx.commit()
    finally:
        ctx.close()
        other.dispose()


def test_no_read_engine_is_the_default(tmp_path: Path):
    scaffold_project(tmp_path / "p")
    config = load_config_at(tmp_path / "p")
    project = Project(config=config, config_store=FileConfigStore(config.project_root))
    assert project.read_engine is None and project.needs_primary is False
    ctx = build_context(project, read_only=True)
    try:
        assert ctx.on_read_engine is False
    finally:
        ctx.close()


class Pair:
    """A primary and a read engine on one scratch schema, recording which one
    ran each statement."""

    def __init__(self, root: Path):
        self.schema = f"ro_{uuid.uuid4().hex[:10]}"
        admin = create_engine(_PG_URL)
        with admin.begin() as c:
            c.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        admin.dispose()
        self.log: list[tuple[str, str]] = []
        self.primary = self._engine("primary")
        self.replica = self._engine("replica")
        ensure_schema_current(self.primary)
        scaffold_project(root)
        config = load_config_at(root)
        self.project = Project(
            config=config,
            config_store=FileConfigStore(root),
            actor="tester",
            engine=self.primary,
            read_engine=self.replica,
            migrated=True,
        )

    def _engine(self, label: str):
        engine = create_engine(
            _PG_URL,
            connect_args={
                "options": f"-csearch_path={self.schema}",
                "application_name": f"civex_u23_{label}",
            },
        )

        @event.listens_for(engine, "before_cursor_execute")
        def _record(conn, cursor, statement, params, context, many):  # noqa: ANN001
            self.log.append((label, statement.split(None, 1)[0].upper()))

        return engine

    def used(self, since: int) -> set[tuple[str, str]]:
        return set(self.log[since:])

    def engines(self, since: int) -> set[str]:
        return {label for label, _ in self.used(since)}

    def close(self):
        self.primary.dispose()
        self.replica.dispose()
        admin = create_engine(_PG_URL)
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        admin.dispose()


@pytest.fixture()
def pair(tmp_path: Path):
    p = Pair(tmp_path / "proj")
    yield p
    p.close()


@pytest.fixture()
def hosted(pair: Pair, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    app = create_app()
    app.state.project_resolver = lambda request: pair.project

    @app.middleware("http")
    async def after_my_write(request, call_next):  # noqa: ANN001
        # What a host does to keep a user on the primary after their own write.
        if request.headers.get("x-after-write"):
            request.state.needs_primary = True
        return await call_next(request)

    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/api/schemas", json={"name": "rock"}).status_code == 201
    client.post("/api/schemas/rock/fields", json={"name": "kind", "type": "string"})
    assert client.post("/api/collections", json={"name": "site"}).status_code == 201
    made = client.post(
        "/api/collections/site/records",
        json={"schema_name": "rock", "data": {"kind": "basalt"}},
    )
    assert made.status_code == 201, made.text
    return client, pair, made.json()["id"]


@needs_pg
def test_reads_use_the_read_engine_and_writes_the_primary(hosted):
    client, pair, record_id = hosted
    reads = [
        "/api/collections",
        "/api/collections/site",
        "/api/collections/site/records",
        "/api/records/all",
        "/api/records/counts",
        f"/api/records/{record_id}",
        "/api/records/search?q=basalt",
        "/api/collections/site/export.csv",
        "/api/analytics/records/counts",
        "/api/schemas/rock/records",
        "/api/records?schema=rock",
        "/api/collections/site/record-counts",
        "/api/analytics/records/growth",
    ]
    for url in reads:
        mark = len(pair.log)
        res = client.get(url)
        assert res.status_code == 200, (url, res.text)
        assert pair.engines(mark) == {"replica"}, url
        assert not {s for _, s in pair.used(mark)} & _WRITES, url

    posts = [
        ("/api/records/summary", {"schema_name": "rock", "group_by": ["kind"]}),
        (
            "/api/schemas/rock/views/preview",
            {"columns": ["kind"], "limit": 10, "offset": 0},
        ),
    ]
    for url, body in posts:
        mark = len(pair.log)
        res = client.post(url, json=body)
        assert res.status_code == 200, (url, res.text)
        assert pair.engines(mark) == {"replica"}, url
        assert not {s for _, s in pair.used(mark)} & _WRITES, url

    mark = len(pair.log)
    res = client.post(
        "/api/collections/site/records", json={"schema_name": "rock", "data": {}}
    )
    assert res.status_code == 201
    assert pair.engines(mark) == {"primary"}
    mark = len(pair.log)
    res = client.patch(f"/api/records/{record_id}", json={"data": {"kind": "shale"}})
    assert res.status_code == 200
    assert pair.engines(mark) == {"primary"}


@needs_pg
def test_routes_not_declared_replica_safe_use_the_primary(hosted):
    client, pair, _ = hosted
    for url in (
        "/api/schemas",
        "/api/audit",
        "/api/sync/hello",
        "/api/sync/snapshot/record",
        "/api/sync/feed",
    ):
        mark = len(pair.log)
        client.get(url)
        assert "replica" not in pair.engines(mark), url


@needs_pg
def test_needs_primary_on_the_request_forces_the_primary(hosted):
    client, pair, record_id = hosted
    mark = len(pair.log)
    assert client.get(f"/api/records/{record_id}").status_code == 200
    assert pair.engines(mark) == {"replica"}
    mark = len(pair.log)
    res = client.get(f"/api/records/{record_id}", headers={"x-after-write": "1"})
    assert res.status_code == 200
    assert pair.engines(mark) == {"primary"}


@needs_pg
def test_needs_primary_on_the_project_forces_the_primary(pair: Pair):
    pair.project.needs_primary = True
    mark = len(pair.log)
    ctx = build_context(pair.project, read_only=True)
    try:
        assert ctx.on_read_engine is False
        ctx.dataset_svc.list_all()
    finally:
        ctx.close()
    assert pair.engines(mark) == {"primary"}


@needs_pg
def test_a_read_context_refuses_writes(pair: Pair):
    ctx = build_context(pair.project, read_only=True)
    try:
        assert ctx.on_read_engine is True
        with pytest.raises(DBAPIError):
            ctx.schema_svc.create("nope")
            ctx.commit()
    finally:
        ctx.close()


@needs_pg
def test_a_normal_context_never_uses_the_read_engine(pair: Pair):
    mark = len(pair.log)
    ctx = build_context(pair.project)
    try:
        assert ctx.on_read_engine is False
        ctx.schema_svc.create("fine")
        with ctx.all_or_nothing():
            ctx.dataset_svc.list_all()
        ctx.commit()
    finally:
        ctx.close()
    assert pair.engines(mark) == {"primary"}


@needs_pg
def test_application_names_tell_the_engines_apart(pair: Pair):
    with pair.replica.connect() as c:
        assert c.execute(text("show application_name")).scalar() == "civex_u23_replica"
    with pair.primary.connect() as c:
        assert c.execute(text("show application_name")).scalar() == "civex_u23_primary"


@needs_pg
def test_an_unreachable_replica_falls_back_to_the_primary(hosted):
    client, pair, record_id = hosted
    pair.project.read_engine = create_engine(
        "postgresql+psycopg2://civexhub@localhost:1/nothing",
        connect_args={"connect_timeout": 1},
    )
    mark = len(pair.log)
    res = client.get(f"/api/records/{record_id}")
    assert res.status_code == 200, res.text
    assert pair.engines(mark) == {"primary"}
