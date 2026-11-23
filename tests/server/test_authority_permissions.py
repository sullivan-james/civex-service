"""Inviting, approving and revoking devices is `MANAGE_DEVICES`, on every
`/remote/authority*` route, answered before the route does anything."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex.config import FileConfigStore, load_config_at
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.project import Project, scaffold_project
from civex.server.app import create_app

ROUTES = [
    ("get", "/api/remote/authority", None),
    ("patch", "/api/remote/authority", {"serving": True}),
    ("post", "/api/remote/authority/invites", {"name": "laptop"}),
    ("post", "/api/remote/authority/invites/laptop/cancel", None),
    ("post", "/api/remote/authority/logins/ABC/approve", {"name": "laptop"}),
    ("post", "/api/remote/authority/logins/ABC/deny", None),
    ("post", "/api/remote/authority/devices/laptop/revoke", None),
    ("post", "/api/remote/authority/devices/laptop/publish", {"allowed": True}),
]


def _client(tmp_path: Path, perms: Permissions) -> TestClient:
    root = tmp_path / "hosted"
    if not root.exists():
        scaffold_project(root)
    app = create_app()
    app.state.project_resolver = lambda request: Project(
        config=load_config_at(root),
        config_store=FileConfigStore(root),
        actor="host",
        permissions=perms,
    )
    return TestClient(app, raise_server_exceptions=False)


def _call(client: TestClient, method: str, url: str, body):
    return client.request(method.upper(), url, json=body)


@pytest.mark.parametrize("method,url,body", ROUTES)
def test_a_caller_without_manage_devices_is_refused(tmp_path, method, url, body):
    everything_else = Permissions(
        {a: frozenset({p.PROJECT}) for a in p.ACTIONS if a != p.MANAGE_DEVICES}
    )
    answer = _call(_client(tmp_path, everything_else), method, url, body)
    assert answer.status_code == 403, (url, answer.text)


@pytest.mark.parametrize("method,url,body", ROUTES)
def test_manage_devices_lets_the_route_run(tmp_path, method, url, body):
    answer = _call(
        _client(tmp_path, Permissions.of(p.READ, p.MANAGE_DEVICES)), method, url, body
    )
    assert answer.status_code != 403, (url, answer.text)


def test_manage_members_has_no_civex_endpoint_to_guard(tmp_path):
    """civex keeps no members: deciding who may do what is the host's. The
    action is in the vocabulary for the host's own use."""
    assert p.MANAGE_MEMBERS in p.ACTIONS
