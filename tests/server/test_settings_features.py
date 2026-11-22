"""A host owns all settings, so it can switch off each settings surface
(`domain.features`): the routes behind a section answer 501 when its feature is
off, and work as before when it is on."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex.config import FileConfigStore, load_config_at
from civex.domain import features as f
from civex.project import Project, scaffold_project
from civex.server.app import create_app

# feature -> requests that belong to its section (method, path, json body)
GATED: dict[str, list[tuple[str, str, dict | None]]] = {
    f.SETTINGS_APPEARANCE: [
        ("GET", "/api/settings/ui", None),
        ("PATCH", "/api/settings/ui", {"show_advanced": True}),
    ],
    f.SETTINGS_MAP: [
        ("GET", "/api/settings/map", None),
    ],
    f.SETTINGS_RETENTION: [
        ("GET", "/api/settings/retention", None),
        ("PATCH", "/api/settings/retention", {"audit_days": 30}),
        ("POST", "/api/retention/run", {"dry_run": True, "from_settings": True}),
        ("POST", "/api/retention/purged-history", {"dry_run": True}),
    ],
    f.SETTINGS_ADVANCED: [
        ("GET", "/api/settings/command-line", None),
    ],
    f.SETTINGS_DEVICES: [
        ("GET", "/api/remote/authority", None),
        ("PATCH", "/api/remote/authority", {"serving": True}),
        ("POST", "/api/remote/authority/invites", {"name": "laptop"}),
        ("POST", "/api/remote/authority/invites/laptop/cancel", None),
        ("POST", "/api/remote/authority/logins/ABC/approve", {"name": "x"}),
        ("POST", "/api/remote/authority/logins/ABC/deny", None),
        ("POST", "/api/remote/authority/devices/laptop/revoke", None),
        ("POST", "/api/remote/authority/devices/laptop/publish", None),
    ],
}


def _client(tmp_path: Path, monkeypatch, features: frozenset[str]) -> TestClient:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "hosted"
    scaffold_project(root)
    app = create_app(features=features)
    app.state.project_resolver = lambda request: Project(
        config=load_config_at(root),
        config_store=FileConfigStore(root),
        actor="host",
        features=features,
    )
    return TestClient(app, raise_server_exceptions=False)


def _send(c: TestClient, method: str, path: str, body):
    return c.request(method, path, json=body)


CASES = [(feat, *req) for feat, reqs in GATED.items() for req in reqs]


@pytest.mark.parametrize(("feature", "method", "path", "body"), CASES)
def test_a_settings_route_refuses_when_its_feature_is_off(
    tmp_path: Path, monkeypatch, feature, method, path, body
):
    c = _client(tmp_path, monkeypatch, f.LOCAL_FEATURES - {feature})
    answer = _send(c, method, path, body)
    assert answer.status_code == 501, answer.text
    assert answer.json()["detail"] == f.unavailable_message(feature)


@pytest.mark.parametrize(("feature", "method", "path", "body"), CASES)
def test_a_settings_route_is_not_refused_when_its_feature_is_on(
    tmp_path: Path, monkeypatch, feature, method, path, body
):
    c = _client(tmp_path, monkeypatch, f.LOCAL_FEATURES)
    assert _send(c, method, path, body).status_code != 501


def test_turning_one_section_off_leaves_the_others(tmp_path: Path, monkeypatch):
    c = _client(tmp_path, monkeypatch, f.LOCAL_FEATURES - {f.SETTINGS_MAP})
    assert c.get("/api/settings/map").status_code == 501
    assert c.get("/api/settings/ui").status_code == 200
    assert c.get("/api/settings/retention").status_code == 200
    assert c.get("/api/remote/authority").status_code == 200


def test_the_host_sees_every_settings_feature(tmp_path: Path, monkeypatch):
    c = _client(tmp_path, monkeypatch, frozenset())
    answer = c.get("/api/status/features").json()
    assert answer["features"] == []
    assert f.SETTINGS_FEATURES <= set(answer["all"])
    assert set(answer["all"]) == set(f.FEATURES)


def test_a_local_project_keeps_every_settings_feature():
    assert f.SETTINGS_FEATURES <= f.LOCAL_FEATURES
    assert f.SETTINGS_FEATURES <= set(f.FEATURES)
