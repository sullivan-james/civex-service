"""POST /db/move and friends: a project moving to another database, driven the
way the browser drives it -- start, poll, read the outcome, revert."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from civex.config import load_config
from civex.services import db_move_service as moves


def _seed(client: TestClient, n: int = 8) -> None:
    client.post("/api/schemas", json={"name": "patient"})
    client.post("/api/schemas/patient/fields", json={"name": "name", "type": "string"})
    client.post("/api/collections", json={"name": "study", "schemas": ["patient"]})
    for i in range(n):
        r = client.post(
            "/api/collections/study/records",
            json={"schema_name": "patient", "data": {"name": f"p{i}"}},
        )
        assert r.status_code == 201, r.text


def _wait(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/db/move/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("move did not finish")


def _target(tmp_path: Path, name: str = "moved.db") -> dict:
    return {"kind": "sqlite", "path": str(tmp_path / name)}


def test_summary_describes_the_current_database(client: TestClient):
    _seed(client)
    body = client.get("/api/db/summary").json()
    assert body["label"] == "SQLite file"
    assert body["records"] == 8 and body["reachable"] is True
    assert body["size_bytes"] > 0


def test_preflight_previews_without_changing_anything(
    client: TestClient, tmp_path: Path
):
    _seed(client)
    before = client.get("/api/db/status").json()["url"]

    body = client.post("/api/db/move/preflight", json=_target(tmp_path)).json()

    assert body["can_proceed"] is True and body["problems"] == []
    assert body["source"]["records"] == 8
    assert body["target"]["rows"] == 0
    assert body["estimate_seconds"] >= 5
    assert not (tmp_path / "moved.db").exists()
    assert client.get("/api/db/status").json()["url"] == before


def test_a_move_runs_in_the_background_and_switches_when_verified(
    client: TestClient, tmp_path: Path
):
    _seed(client)

    started = client.post("/api/db/move", json=_target(tmp_path))
    assert started.status_code == 202
    done = _wait(client, started.json()["id"])

    assert done["status"] == "done", done
    assert done["record"]["counts"]["records"] == 8
    assert done["progress"]["rows_done"] == done["progress"]["rows_total"] > 0
    assert client.get("/api/db/status").json()["url"].endswith("moved.db")
    # The data is there, in the new database, through the normal API.
    listed = client.get("/api/collections/study/records", params={"schema": "patient"})
    assert listed.json()["total"] == 8
    assert "from_url" not in done["record"] and "to_url" not in done["record"]


def test_history_lists_moves_and_a_move_can_be_reverted(
    client: TestClient, tmp_path: Path
):
    _seed(client)
    original = client.get("/api/db/status").json()["url"]
    job = _wait(
        client, client.post("/api/db/move", json=_target(tmp_path)).json()["id"]
    )

    history = client.get("/api/db/moves").json()
    assert [m["id"] for m in history] == [job["record"]["id"]]
    assert history[0]["status"] == "done" and history[0]["reverted_at"] is None

    reverted = client.post(f"/api/db/moves/{job['record']['id']}/revert")
    assert reverted.status_code == 200
    assert reverted.json()["url"] == original
    assert client.get("/api/db/moves").json()[0]["reverted_at"]
    again = client.post(f"/api/db/moves/{job['record']['id']}/revert")
    assert again.status_code == 422 and "already reverted" in again.json()["detail"]


def test_a_destination_that_has_data_is_refused_up_front(
    client: TestClient, tmp_path: Path
):
    _seed(client)
    first = _wait(
        client, client.post("/api/db/move", json=_target(tmp_path)).json()["id"]
    )
    assert first["status"] == "done"
    old_url = moves.list_moves(load_config())[0].from_url  # the full database we left

    refused = client.post("/api/db/move", json={"kind": "postgres", "url": old_url})

    assert refused.status_code == 422
    assert "isn't empty" in refused.json()["detail"]


def test_unknown_jobs_are_404(client: TestClient):
    assert client.get("/api/db/move/nope").status_code == 404
    assert client.post("/api/db/move/nope/cancel").status_code == 404


def test_connection_problems_are_explained_in_plain_words(client: TestClient):
    body = client.post(
        "/api/db/test-connection",
        json={
            "kind": "postgres",
            "host": "127.0.0.1",
            "port": 1,
            "database": "x",
            "user": "u",
        },
    ).json()
    assert body["ok"] is False
    assert "Nothing answered" in body["error"] or "driver" in body["error"].lower()


def test_missing_connection_details_say_what_is_needed(client: TestClient):
    body = client.post("/api/db/test-connection", json={"kind": "postgres"}).json()
    assert body["ok"] is False and "host and a database" in body["error"]


def test_explain_connection_error_translates_common_failures():
    f = moves.explain_connection_error
    assert "user name or password" in f(
        'FATAL:  password authentication failed for user "a"'
    )
    assert "doesn't exist" in f('FATAL:  database "x" does not exist')
    assert "Nothing answered" in f(
        "connection to server at 'h', port 5432 failed: Connection refused"
    )
    assert "host name" in f("could not translate host name 'nope' to address")
    assert f("something odd\nsecond line") == "something odd"
