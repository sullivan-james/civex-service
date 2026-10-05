"""HTTP contract of /api/remote/*: following an authority from the app."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_a_project_that_follows_nothing_says_so(client: TestClient) -> None:
    body = client.get("/api/remote").json()
    assert body["configured"] is False
    assert body["pending"] == 0 and body["open_conflicts"] == 0


def test_pausing_and_the_interval_are_kept(client: TestClient) -> None:
    resp = client.patch("/api/remote", json={"paused": True, "interval_seconds": 120})
    assert resp.status_code == 200, resp.text
    again = client.get("/api/remote").json()
    assert again["paused"] is True and again["interval_seconds"] == 120


def test_an_interval_under_five_seconds_is_refused(client: TestClient) -> None:
    assert client.patch("/api/remote", json={"interval_seconds": 1}).status_code == 422


def test_syncing_now_needs_an_authority(client: TestClient) -> None:
    assert client.post("/api/remote/sync").status_code == 400


def test_connecting_to_nothing_is_a_bad_gateway(client: TestClient) -> None:
    resp = client.post(
        "/api/remote/connect", json={"url": "http://127.0.0.1:9", "token": "x"}
    )
    assert resp.status_code == 502


def test_no_conflicts_on_a_fresh_project(client: TestClient) -> None:
    assert client.get("/api/remote/conflicts").json() == []
    bad = client.post("/api/remote/conflicts/nope/resolve", json={"take": "mine"})
    assert bad.status_code == 422


def test_never_is_an_interval_of_zero(client: TestClient) -> None:
    assert client.patch("/api/remote", json={"interval_seconds": 0}).status_code == 200
    assert client.get("/api/remote").json()["interval_seconds"] == 0


def test_the_name_changes_are_recorded_under_can_be_chosen(client: TestClient) -> None:
    first = client.get("/api/settings/identity").json()
    assert first["chosen"] is None
    saved = client.patch("/api/settings/identity", json={"name": "Dana"}).json()
    assert saved["name"] == "Dana" and saved["chosen"] == "Dana"
    back = client.patch("/api/settings/identity", json={"name": None}).json()
    assert back["chosen"] is None and back["name"] == back["default"]
