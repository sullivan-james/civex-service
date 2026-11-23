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

# feature -> requests that edit that section's stored settings (method, path,
# json body). Operational routes a host drives itself are not here: see
# OPERATIONS below.
GATED: dict[str, list[tuple[str, str, dict | None]]] = {
    f.SETTINGS_APPEARANCE: [
        ("PATCH", "/api/settings/ui", {"show_advanced": True}),
    ],
    f.SETTINGS_MAP: [
        ("PATCH", "/api/settings/map", {"tile_url": None}),
    ],
    f.SETTINGS_RETENTION: [
        ("PATCH", "/api/settings/retention", {"audit_days": 30}),
    ],
    f.SETTINGS_ADVANCED: [
        ("POST", "/api/settings/command-line", {}),
        ("DELETE", "/api/settings/command-line", None),
    ],
}


# Routes of a section that are not settings edits: a host's own UI calls them,
# so no settings feature may refuse them.
OPERATIONS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/remote/authority", None),
    ("PATCH", "/api/remote/authority", {"serving": True}),
    ("POST", "/api/remote/authority/invites", {"name": "laptop"}),
    ("POST", "/api/remote/authority/invites/laptop/cancel", None),
    ("POST", "/api/remote/authority/logins/ABC/approve", {"name": "x"}),
    ("POST", "/api/remote/authority/logins/ABC/deny", None),
    ("POST", "/api/remote/authority/devices/laptop/revoke", None),
    ("POST", "/api/remote/authority/devices/laptop/publish", None),
    ("POST", "/api/retention/run", {"dry_run": True, "from_settings": True}),
    ("POST", "/api/retention/purged-history", {"dry_run": True}),
]


def _client(tmp_path: Path, monkeypatch, features: frozenset[str]) -> TestClient:
    tmp_path.mkdir(exist_ok=True)
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
# Not run where the feature is on: the command-line routes change the real PATH.
ON_CASES = [c for c in CASES if "command-line" not in c[2]]
READS = [
    "/api/settings/ui",
    "/api/settings/map",
    "/api/settings/retention",
    "/api/settings/command-line",
    "/api/settings/identity",
]


@pytest.mark.parametrize(("feature", "method", "path", "body"), CASES)
def test_a_settings_route_refuses_when_its_feature_is_off(
    tmp_path: Path, monkeypatch, feature, method, path, body
):
    c = _client(tmp_path, monkeypatch, f.LOCAL_FEATURES - {feature})
    answer = _send(c, method, path, body)
    assert answer.status_code == 501, answer.text
    assert answer.json()["detail"] == f.unavailable_message(feature)


@pytest.mark.parametrize(("feature", "method", "path", "body"), ON_CASES)
def test_a_settings_route_is_not_refused_when_its_feature_is_on(
    tmp_path: Path, monkeypatch, feature, method, path, body
):
    c = _client(tmp_path, monkeypatch, f.LOCAL_FEATURES)
    assert _send(c, method, path, body).status_code != 501


@pytest.mark.parametrize(("method", "path", "body"), OPERATIONS)
def test_no_settings_feature_refuses_an_operation_a_host_drives(
    tmp_path: Path, monkeypatch, method, path, body
):
    c = _client(tmp_path, monkeypatch, f.LOCAL_FEATURES - f.SETTINGS_FEATURES)
    assert _send(c, method, path, body).status_code != 501


@pytest.mark.parametrize("path", READS)
def test_reading_a_setting_is_never_refused(tmp_path: Path, monkeypatch, path):
    """The app reads these everywhere (the map view, the advanced display), so a
    host turning settings off refuses only edits."""
    c = _client(tmp_path, monkeypatch, f.LOCAL_FEATURES - f.SETTINGS_FEATURES)
    assert c.get(path).status_code != 501


def test_turning_one_section_off_leaves_the_others(tmp_path: Path, monkeypatch):
    c = _client(tmp_path, monkeypatch, f.LOCAL_FEATURES - {f.SETTINGS_MAP})
    off = c.patch("/api/settings/map", json={"tile_url": None})
    assert off.status_code == 501
    on = c.patch("/api/settings/ui", json={"show_advanced": True})
    assert on.status_code == 200
    assert (
        c.patch("/api/settings/retention", json={"audit_days": 30}).status_code == 200
    )


@pytest.mark.parametrize(("feature", "method", "path", "body"), CASES)
def test_the_settings_umbrella_turns_every_section_off(
    tmp_path: Path, monkeypatch, feature, method, path, body
):
    """`settings` off counts each section as off, whatever its own feature."""
    c = _client(tmp_path, monkeypatch, f.LOCAL_FEATURES - {f.SETTINGS})
    answer = _send(c, method, path, body)
    assert answer.status_code == 501, answer.text
    assert answer.json()["detail"] == f.unavailable_message(f.SETTINGS)


def test_identity_is_edited_only_where_settings_are_on(tmp_path: Path, monkeypatch):
    off = _client(tmp_path / "off", monkeypatch, f.LOCAL_FEATURES - {f.SETTINGS})
    answer = off.patch("/api/settings/identity", json={"name": "Dr Example"})
    assert answer.status_code == 501
    assert off.get("/api/settings/identity").status_code == 200
    on = _client(tmp_path / "on", monkeypatch, f.LOCAL_FEATURES)
    answer = on.patch("/api/settings/identity", json={"name": "Dr Example"})
    assert answer.status_code == 200


def test_enabled_applies_the_umbrella_to_sections_only():
    sections = f.SETTINGS_FEATURES - {f.SETTINGS}
    on = frozenset({f.SETTINGS, f.SETTINGS_MAP})
    assert f.enabled(on, f.SETTINGS_MAP)
    assert not f.enabled(on, f.SETTINGS_RETENTION)
    umbrella_off = frozenset(sections | {f.TERMINAL})
    assert not any(f.enabled(umbrella_off, x) for x in sections)
    assert f.enabled(umbrella_off, f.TERMINAL)
    assert f.lacks(umbrella_off, f.SETTINGS_MAP) == f.SETTINGS


def test_the_host_sees_every_settings_feature(tmp_path: Path, monkeypatch):
    c = _client(tmp_path, monkeypatch, frozenset())
    answer = c.get("/api/status/features").json()
    assert answer["features"] == []
    assert f.SETTINGS_FEATURES <= set(answer["all"])
    assert set(answer["all"]) == set(f.FEATURES)


def test_a_local_project_keeps_every_settings_feature():
    assert f.SETTINGS_FEATURES <= f.LOCAL_FEATURES
    assert f.SETTINGS_FEATURES <= set(f.FEATURES)
