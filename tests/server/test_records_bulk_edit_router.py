"""POST /records/bulk-edit and its plan: fields set on many records at once,
by id or by the same query a list shows."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _post(client: TestClient, url: str, body: dict) -> dict:
    resp = client.post(url, json=body)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _setup(client: TestClient) -> list[dict]:
    _post(client, "/api/schemas", {"name": "trial"})
    _post(client, "/api/schemas/trial/fields", {"name": "subject", "type": "string"})
    _post(
        client,
        "/api/schemas/trial/fields",
        {"name": "dose", "type": "integer", "restrictions": {"max": 10}},
    )
    _post(client, "/api/collections", {"name": "study"})
    return [
        _post(
            client,
            "/api/collections/study/records",
            {"schema_name": "trial", "data": {"subject": f"S{i}"}},
        )
        for i in range(3)
    ]


def test_the_plan_says_what_would_change_and_the_edit_does_it(client: TestClient):
    trials = _setup(client)
    ids = [t["id"] for t in trials]

    plan = _post(
        client, "/api/records/bulk-edit/plan", {"ids": ids, "changes": {"dose": 5}}
    )
    assert plan["can_apply"] is True
    assert (plan["records"], plan["changing"], plan["skipped"]) == (3, 3, 0)

    done = _post(client, "/api/records/bulk-edit", {"ids": ids, "changes": {"dose": 5}})
    assert (done["changed"], done["unchanged"], done["skipped"]) == (3, 0, 0)
    for t in trials:
        assert client.get(f"/api/records/{t['id']}").json()["data"]["dose"] == 5

    cleared = _post(
        client, "/api/records/bulk-edit", {"ids": ids[:1], "changes": {"dose": None}}
    )
    assert cleared["changed"] == 1
    got = client.get(f"/api/records/{ids[0]}").json()["data"]
    assert got.get("dose") is None


def test_a_query_edits_what_the_list_shows_and_bad_values_are_named(
    client: TestClient,
):
    _setup(client)
    body = {
        "collection": "study",
        "schema_name": "trial",
        "search": "S1",
        "changes": {"dose": 99},
    }
    plan = _post(client, "/api/records/bulk-edit/plan", body)
    assert (plan["records"], plan["skipped"], plan["can_apply"]) == (1, 1, False)
    assert plan["skipped_records"][0]["name"] == "S1"
    assert "dose" in plan["skipped_records"][0]["reason"]


def test_no_records_or_no_changes_is_a_422(client: TestClient):
    _setup(client)
    resp = client.post("/api/records/bulk-edit/plan", json={"changes": {"dose": 1}})
    assert resp.status_code == 422
    resp = client.post(
        "/api/records/bulk-edit", json={"collection": "study", "changes": {}}
    )
    assert resp.status_code == 422
