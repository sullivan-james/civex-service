"""Releases belong to a host: `features.RELEASES` is off for a project on this
machine (every release route answers 404), and `RELEASE` is the permission to
make, correct, withdraw and yank one, which `change_structure` implies."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex.config import FileConfigStore, load_config_at
from civex.domain import features as f
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.project import Project
from civex.server.app import create_app

ON = f.LOCAL_FEATURES | {f.RELEASES}

ROUTES = [
    ("get", "/api/releases", None),
    ("post", "/api/releases/plan", {}),
    ("post", "/api/releases/citation-preview", {"name": "v1", "title": "x"}),
    ("post", "/api/releases", {"name": "v1", "title": "x"}),
    ("get", "/api/releases/v1", None),
    ("patch", "/api/releases/v1", {"title": "y"}),
    ("post", "/api/releases/v1/withdraw", {"reason": "r"}),
    ("get", "/api/releases/v1/yank", None),
    ("post", "/api/releases/v1/yank", {"reason": "r"}),
    ("get", "/api/releases/v1/citation", None),
    ("post", "/api/releases/v1/verify", None),
    ("post", "/api/releases/v1/files/plan", {}),
    ("post", "/api/releases/v1/files/export", {"mode": "copy"}),
    ("post", "/api/releases/v1/files/zip", {}),
    ("post", "/api/releases/v1/compare", None),
    ("get", "/api/releases/v1/compare/records?kind=added", None),
    ("get", "/api/releases/v1/bundle", None),
]


def test_this_machine_does_not_offer_releases():
    assert f.RELEASES not in f.LOCAL_FEATURES
    assert f.RELEASES in f.FEATURES


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_every_release_route_is_404_when_the_feature_is_off(
    client: TestClient, method: str, path: str, body: dict | None
):
    kwargs = {} if body is None else {"json": body}
    answer = getattr(client, method)(path, **kwargs)
    # Not there: 404 (a built app's catch-all answers a POST 405, which is the
    # same "no such route").
    assert answer.status_code == (404 if method == "get" else answer.status_code)
    assert answer.status_code in (404, 405), (path, answer.text)
    assert f.RELEASES not in client.get("/api/status/features").json()["features"]


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_the_routes_exist_when_the_host_offers_the_feature(
    releases_client: TestClient, method: str, path: str, body: dict | None
):
    kwargs = {} if body is None else {"json": body}
    answer = getattr(releases_client, method)(path, **kwargs)
    # Whatever it says about this release (it isn't there), the route is.
    assert answer.status_code != 501, path
    assert answer.status_code != 404 or "Release" in answer.text, path
    assert f.RELEASES in releases_client.get("/api/status/features").json()["features"]


def test_a_project_without_the_feature_is_refused_even_where_the_router_is_mounted(
    project_dir: Path,
):
    app = create_app(features=ON)
    app.state.project_resolver = lambda request: Project.local(
        load_config_at(project_dir)
    )
    answer = TestClient(app, raise_server_exceptions=False).get("/api/releases")
    assert answer.status_code == 501
    assert answer.json()["detail"] == f.unavailable_message(f.RELEASES)


def _host(project_dir: Path, perms: Permissions) -> TestClient:
    app = create_app(features=ON)
    app.state.project_resolver = lambda request: Project(
        config=load_config_at(project_dir),
        config_store=FileConfigStore(project_dir),
        actor="host",
        features=ON,
        permissions=perms,
    )
    return TestClient(app, raise_server_exceptions=False)


def _make(client: TestClient, name: str = "v1"):
    return client.post("/api/releases", json={"name": name, "title": "Survey"})


def test_a_role_that_changes_structure_may_release_unless_the_host_says_not(
    project_dir: Path,
):
    old_role = Permissions.of(p.READ, p.CHANGE_STRUCTURE)
    assert _make(_host(project_dir, old_role)).status_code == 201
    withheld = old_role.lacking(p.RELEASE)
    refused = _make(_host(project_dir, withheld), "v2")
    assert refused.status_code == 403
    assert "release" in refused.json()["detail"]


def test_release_alone_makes_corrects_withdraws_and_yanks_but_edits_no_structure(
    project_dir: Path,
):
    only = _host(project_dir, Permissions.of(p.READ, p.RELEASE))
    assert _make(only).status_code == 201
    assert only.patch("/api/releases/v1", json={"title": "New"}).status_code == 200
    gone = only.post("/api/releases/v1/withdraw", json={"reason": "r"})
    assert gone.status_code == 200
    assert only.post("/api/releases/v1/yank", json={"reason": "r"}).status_code == 200
    assert only.post("/api/schemas", json={"name": "sample"}).status_code == 403


def test_a_reader_may_read_but_not_make_correct_withdraw_or_yank(project_dir: Path):
    owner = _host(project_dir, Permissions.everything())
    assert _make(owner).status_code == 201
    reader = _host(project_dir, Permissions.of(p.READ))
    assert reader.get("/api/releases/v1").status_code == 200
    assert _make(reader, "v2").status_code == 403
    assert reader.patch("/api/releases/v1", json={"title": "x"}).status_code == 403
    gone = reader.post("/api/releases/v1/withdraw", json={"reason": "r"})
    assert gone.status_code == 403
    assert reader.post("/api/releases/v1/yank", json={"reason": "r"}).status_code == 403
