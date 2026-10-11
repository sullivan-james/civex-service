"""A server serves whichever project `current_project` resolves, not the one
in its working directory.

`civex serve` hosts the project in its directory. A host serving many projects
installs `app.state.project_resolver`, and every route, context, saved setting
and recorded author follows it. These tests are the contract that host builds on.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex.config import FileConfigStore, load_config_at
from civex.context import build_context, build_local_context
from civex.project import Project, scaffold_project
from civex.server.app import create_app


@pytest.fixture()
def hosted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Two projects served by one app, chosen per request by an `X-Project`
    header. The working directory holds no project, so nothing may fall back
    to it."""
    monkeypatch.chdir(tmp_path)
    roots = {name: tmp_path / name for name in ("alpha", "beta")}
    for root in roots.values():
        scaffold_project(root)

    app = create_app()

    def resolve(request) -> Project:  # noqa: ANN001 - Request
        name = request.headers.get("x-project", "alpha")
        root = roots[name]
        return Project(
            config=load_config_at(root),
            config_store=FileConfigStore(root),
            actor=f"{name} person",
        )

    app.state.project_resolver = resolve
    return TestClient(app, raise_server_exceptions=False), roots


def _on(name: str) -> dict[str, str]:
    return {"X-Project": name}


def test_each_request_is_served_from_the_project_resolved_for_it(hosted):
    client, _ = hosted
    made = client.post("/api/schemas", json={"name": "trial"}, headers=_on("alpha"))
    assert made.status_code == 201, made.text

    assert [
        s["name"] for s in client.get("/api/schemas", headers=_on("alpha")).json()
    ] == ["trial"]
    assert client.get("/api/schemas", headers=_on("beta")).json() == []


def test_a_change_is_recorded_as_the_actor_the_host_named(hosted):
    client, roots = hosted
    assert (
        client.post(
            "/api/schemas", json={"name": "trial"}, headers=_on("beta")
        ).status_code
        == 201
    )

    ctx = build_local_context(load_config_at(roots["beta"]))
    try:
        events = ctx.history_svc.page(limit=5)
    finally:
        ctx.close()
    assert events and events[0].actor == "beta person"


def test_settings_are_saved_where_the_resolved_project_keeps_them(hosted):
    client, roots = hosted
    changed = client.patch(
        "/api/settings/identity", json={"name": "Dr Beta"}, headers=_on("beta")
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["chosen"] == "Dr Beta"

    def chosen(root: Path) -> str | None:
        data = tomllib.loads((root / "_civex" / "config.toml").read_text())
        return data.get("identity", {}).get("name")

    assert chosen(roots["beta"]) == "Dr Beta"
    assert chosen(roots["alpha"]) is None
    assert (
        client.get("/api/settings/identity", headers=_on("alpha")).json()["chosen"]
        is None
    )


def test_the_settings_routes_need_no_database(hosted):
    """The database router answers from the project's settings alone, so it
    still works when the database it names can't be opened."""
    client, _ = hosted
    status = client.get("/api/db/status", headers=_on("alpha"))
    assert status.status_code == 200
    assert status.json()["dialect"] == "sqlite"


def test_a_host_may_share_an_engine_and_skip_the_schema_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A host that migrated every project at deploy passes `migrated=True`
    and its own engine; the context then neither makes an engine nor checks
    the schema on every request."""
    from sqlalchemy import create_engine

    from civex.db import migrate
    from civex.db.engine import enable_sqlite_foreign_keys

    root = tmp_path / "hosted"
    scaffold_project(root)
    config = load_config_at(root)
    engine = enable_sqlite_foreign_keys(create_engine(config.db.url))

    def never(*_args, **_kwargs):
        raise AssertionError("the schema check must not run for a migrated project")

    monkeypatch.setattr(migrate, "ensure_schema_current", never)

    ctx = build_context(
        Project(
            config=config,
            config_store=FileConfigStore(root),
            actor="host",
            engine=engine,
            migrated=True,
        )
    )
    try:
        assert ctx.schema_svc.list_all() == []
        assert ctx._session.get_bind() is engine
    finally:
        ctx.close()
        engine.dispose()


def test_without_a_resolver_the_working_directory_project_is_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "here"
    scaffold_project(root)
    monkeypatch.chdir(root)
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get("/api/schemas").json() == []
    assert client.get("/api/settings/identity").status_code == 200
