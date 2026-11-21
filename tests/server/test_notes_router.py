"""HTTP contract for notes on records, their threads, and finding what is open."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _study(client: TestClient) -> list[str]:
    client.post("/api/schemas", json={"name": "sample"})
    client.post("/api/schemas/sample/fields", json={"name": "site", "type": "string"})
    client.post("/api/collections", json={"name": "survey"})
    ids = []
    for site in ("a", "b", "c"):
        made = client.post(
            "/api/collections/survey/records",
            json={"schema_name": "sample", "data": {"site": site}},
        )
        assert made.status_code == 201, made.text
        ids.append(made.json()["id"])
    return ids


def test_notes_are_added_listed_edited_resolved_and_deleted(client: TestClient):
    a, _, _ = _study(client)
    made = client.post(f"/api/records/{a}/notes", json={"body": "depth looks off"})
    assert made.status_code == 201, made.text
    note = made.json()
    assert note["body"] == "depth looks off" and note["resolved_at"] is None
    assert client.get(f"/api/records/{a}").json()["open_notes"] == 1
    counted = client.post(
        "/api/records/open-notes",
        json={"collection": "survey", "schema_name": "sample"},
    )
    assert counted.json() == {"notes": 1, "records": 1}

    edited = client.patch(f"/api/notes/{note['id']}", json={"body": "re-check"})
    assert edited.json()["edited_at"] is not None
    resolved = client.post(f"/api/notes/{note['id']}/resolve", json={"resolved": True})
    assert resolved.json()["resolved_at"] is not None
    listed = client.get(f"/api/records/{a}/notes", params={"include_resolved": False})
    assert listed.json() == []
    assert client.delete(f"/api/notes/{note['id']}").status_code == 200
    assert client.get(f"/api/records/{a}/notes").json() == []
    assert client.post(f"/api/notes/{note['id']}/restore").status_code == 200
    assert len(client.get(f"/api/records/{a}/notes").json()) == 1

    empty = client.post(f"/api/records/{a}/notes", json={"body": "  "})
    assert empty.status_code == 422
    missing = client.post("/api/records/ffffffff/notes", json={"body": "hello"})
    assert missing.status_code == 404


def test_replies_make_a_thread_and_open_threads_are_found(client: TestClient):
    a, b, _ = _study(client)
    note = client.post(
        f"/api/records/{a}/notes", json={"body": "depth looks off\nsee log"}
    ).json()
    client.post(f"/api/records/{b}/notes", json={"body": "fine"})
    done = client.get(f"/api/records/{b}/notes").json()[0]
    client.post(f"/api/notes/{done['id']}/resolve")

    reply = client.post(f"/api/notes/{note['id']}/replies", json={"body": "fixed"})
    assert reply.status_code == 201, reply.text
    assert reply.json()["thread_id"] == note["id"]
    again = client.post(f"/api/notes/{reply.json()['id']}/replies", json={"body": "ok"})
    assert again.json()["thread_id"] == note["id"]
    (thread,) = client.get(f"/api/records/{a}/notes").json()
    assert [r["body"] for r in thread["replies"]] == ["fixed", "ok"]

    record = client.get(f"/api/records/{a}").json()
    assert (record["open_notes"], record["latest_note"]) == (1, "depth looks off")
    listed = client.get(
        "/api/schemas/sample/records",
        params={
            "filter": json.dumps({"field": "@open_notes", "op": "eq", "value": True}),
            "columns": "@open_notes",
        },
    )
    assert listed.status_code == 200, listed.text
    assert [r["id"] for r in listed.json()["items"]] == [a]
    assert listed.json()["items"][0]["latest_note"] == "depth looks off"
    bad = client.get(
        "/api/schemas/sample/records",
        params={
            "filter": json.dumps({"field": "@open_notes", "op": "eq", "value": "yes"})
        },
    )
    assert bad.status_code == 422
