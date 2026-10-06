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
    assert client.get("/api/settings/identity").json()["chosen"] == "Dana"
    back = client.patch("/api/settings/identity", json={"name": None}).json()
    assert back["chosen"] is None and back["name"] == back["default"]


def test_a_conflict_that_moved_on_answers_409_with_what_is_there_now(
    client: TestClient,
) -> None:
    """Putting a value back refuses, and says what is on the record now, when it
    changed since the conflict was recorded."""
    from civex.domain.exceptions import ConflictMovedError
    from civex.server.errors import _status_for

    assert _status_for(ConflictMovedError("moved", "newer")) == 409


def test_settling_many_with_nothing_open_settles_nothing(client: TestClient) -> None:
    body = client.post("/api/remote/conflicts/resolve-many", json={"take": "theirs"})
    assert body.status_code == 200, body.text
    assert body.json() == {"done": 0, "settled_ids": [], "not_offered": 0, "failed": []}
    assert (
        client.post(
            "/api/remote/conflicts/resolve-many", json={"take": "theirs", "ids": ["no"]}
        ).status_code
        == 422
    )
    # A typed value is one per conflict, so it is not a bulk way.
    assert (
        client.post(
            "/api/remote/conflicts/resolve-many", json={"take": "value"}
        ).status_code
        == 422
    )


def test_reopening_nothing_reopens_nothing(client: TestClient) -> None:
    resp = client.post("/api/remote/conflicts/reopen", json={"ids": []})
    assert resp.json() == {"reopened": 0}


def test_connecting_again_without_a_token_needs_one_held_here(
    client: TestClient,
) -> None:
    resp = client.post("/api/remote/connect", json={"url": "http://127.0.0.1:9"})
    assert resp.status_code == 400
    assert "token" in resp.json()["detail"]


def test_history_storage_says_what_is_left_and_reclaims(client: TestClient) -> None:
    body = client.get("/api/audit/storage").json()
    assert body["whole_entries"] == 0 and body["converting"] is False
    assert body["size_bytes"] > 0
    again = client.post("/api/audit/storage/reclaim")
    assert again.status_code == 200, again.text
    assert again.json()["free_bytes"] == 0


def test_the_app_serves_and_issues_tokens_as_the_cli_does(client: TestClient) -> None:
    on = client.patch("/api/remote/authority", json={"serving": True}).json()
    assert on["serving"] is True and on["devices"] == []
    issued = client.post("/api/remote/authority/devices", json={"name": "laptop"})
    assert issued.status_code == 200, issued.text
    assert issued.json()["token"] and issued.json()["devices"][0]["name"] == "laptop"
    again = client.post("/api/remote/authority/devices", json={"name": "laptop"})
    assert again.status_code == 422
    revoked = client.post("/api/remote/authority/devices/laptop/revoke").json()
    assert revoked["devices"][0]["revoked"] is True
    assert client.post("/api/remote/authority/devices/laptop/revoke").status_code == 404
    assert client.get("/api/remote").json()["serving"] is True
