"""POST /records/move and its plan: records re-pointed at another collection,
by id or by the same query a list shows."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _post(client: TestClient, url: str, body: dict) -> dict:
    resp = client.post(url, json=body)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _setup(client: TestClient) -> tuple[dict, dict]:
    _post(client, "/api/schemas", {"name": "site"})
    _post(client, "/api/schemas/site/fields", {"name": "name", "type": "string"})
    _post(client, "/api/schemas", {"name": "visit", "parent": "site"})
    _post(client, "/api/collections", {"name": "survey"})
    _post(client, "/api/collections", {"name": "archive"})
    site = _post(
        client,
        "/api/collections/survey/records",
        {"schema_name": "site", "data": {"name": "a"}},
    )
    visit = _post(
        client,
        "/api/collections/survey/records",
        {"schema_name": "visit", "data": {}, "parent_record_id": site["id"]},
    )
    return site, visit


def test_the_plan_says_what_would_move_and_the_move_does_it(client: TestClient):
    site, visit = _setup(client)

    plan = _post(
        client, "/api/records/move/plan", {"to": "archive", "ids": [site["id"]]}
    )
    assert plan["can_move"] is True
    assert (plan["roots"], plan["records"], plan["sources"]) == (1, 2, ["survey"])
    assert plan["collection"] == "archive" and plan["problems"] == []

    moved = _post(client, "/api/records/move", {"to": "archive", "ids": [site["id"]]})
    assert moved == {"roots": 1, "records": 2, "collection": "archive"}
    for record in (site, visit):
        got = client.get(f"/api/records/{record['id']}").json()
        assert got["collection"] == "archive"
    assert client.get("/api/collections/survey").json()["record_count"] == 0


def test_a_query_moves_exactly_what_a_list_with_it_shows(client: TestClient):
    _setup(client)
    _post(
        client,
        "/api/collections/survey/records",
        {"schema_name": "site", "data": {"name": "b"}},
    )
    body = {
        "to": "archive",
        "collection": "survey",
        "schema_name": "site",
        "filter": {"field": "name", "op": "eq", "value": "b"},
    }
    assert _post(client, "/api/records/move/plan", body)["roots"] == 1
    assert _post(client, "/api/records/move", body)["records"] == 1
    assert client.get("/api/collections/survey").json()["record_count"] == 2


def test_a_move_in_the_way_is_refused_with_the_reason(client: TestClient):
    _, visit = _setup(client)
    body = {"to": "archive", "ids": [visit["id"]]}
    plan = _post(client, "/api/records/move/plan", body)
    assert plan["can_move"] is False
    assert plan["problems"] == [
        "A Visit sits inside a Site: choose the Site it goes in."
    ]

    resp = client.post("/api/records/move", json=body)
    assert resp.status_code == 422
    assert "choose the Site" in resp.json()["detail"]


def test_moving_inside_a_record_of_the_target(client: TestClient):
    site, visit = _setup(client)
    other = _post(
        client,
        "/api/collections/archive/records",
        {"schema_name": "site", "data": {"name": "b"}},
    )
    moved = _post(
        client,
        "/api/records/move",
        {"to": "archive", "parent": other["id"][:8], "ids": [visit["id"]]},
    )
    assert moved["records"] == 1
    got = client.get(f"/api/records/{visit['id']}").json()
    assert got["parent_record_id"] == other["id"]


def test_the_request_needs_ids_or_a_collection(client: TestClient):
    _setup(client)
    resp = client.post("/api/records/move", json={"to": "archive"})
    assert resp.status_code == 422
    resp = client.post("/api/records/move", json={"to": "nowhere", "ids": ["x"]})
    assert resp.status_code == 404
