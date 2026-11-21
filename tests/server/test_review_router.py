"""HTTP contract for review status and notes on records."""

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


def test_records_are_marked_by_ids_or_query_and_filtered(client: TestClient):
    a, b, c = _study(client)
    marked = client.post(
        "/api/records/review", json={"ids": [a, b], "status": "needs_check"}
    )
    assert marked.status_code == 200, marked.text
    assert marked.json() == {
        "status": "needs_check",
        "records": 2,
        "changed": 2,
        "unchanged": 0,
    }
    record = client.get(f"/api/records/{a}").json()
    assert record["review"]["status"] == "needs_check"

    planned = client.post(
        "/api/records/review",
        json={
            "collection": "survey",
            "schema_name": "sample",
            "status": "checked",
            "dry_run": True,
        },
    )
    assert planned.json()["changed"] == 3
    assert client.get(f"/api/records/{c}").json()["review"] is None

    waiting = client.get(
        "/api/collections/survey/records",
        params={
            "schema": "sample",
            "filter": json.dumps(
                {"field": "@review", "op": "eq", "value": "needs_check"}
            ),
            "columns": "@review",
        },
    )
    assert waiting.status_code == 200, waiting.text
    assert sorted(r["id"] for r in waiting.json()["items"]) == sorted([a, b])

    bad = client.post("/api/records/review", json={"ids": [a], "status": "maybe"})
    assert bad.status_code == 422


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
