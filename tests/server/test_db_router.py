"""HTTP contract for /api/db/*. These routes deliberately don't use
Depends(get_ctx) -- they must keep responding even when the configured
database is unreachable, since that's exactly the situation a "database
settings" surface exists to help with. Docker setup/teardown aren't covered
here since they need a real Docker daemon; verified manually.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_get_status_on_a_fresh_project(client: TestClient) -> None:
    resp = client.get("/api/db/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dialect"] == "sqlite"
    assert body["docker_managed"] is False
    assert body["docker"] is None
    assert body["migration"]["up_to_date"] is True
    assert body["migration"]["error"] is None


def test_migrate_is_a_noop_when_already_current(client: TestClient) -> None:
    resp = client.post("/api/db/migrate")
    assert resp.status_code == 200
    assert resp.json()["migration"]["up_to_date"] is True


def test_patch_config_switches_to_a_new_sqlite_file(
    client: TestClient, project_dir: Path
) -> None:
    new_url = f"sqlite:///{project_dir / 'other.db'}"
    resp = client.patch("/api/db/config", json={"url": new_url})
    assert resp.status_code == 200
    assert resp.json()["url"] == new_url

    # The switch persisted -- a follow-up status call reflects it.
    status = client.get("/api/db/status").json()
    assert status["url"] == new_url


def test_patch_config_rejects_an_unparseable_url(client: TestClient) -> None:
    resp = client.patch("/api/db/config", json={"url": "not-a-real-url://nope"})
    assert resp.status_code == 422
    assert "Could not connect" in resp.json()["detail"]
