"""Uniqueness policies over HTTP: defining them, being refused by them, and
restoring a record whose values were taken meanwhile."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _setup(client: TestClient) -> None:
    client.post(
        "/api/schemas",
        json={
            "name": "plot",
            "fields": [
                {"name": "site", "type": "string"},
                {"name": "number", "type": "integer"},
            ],
        },
    )
    client.post("/api/collections", json={"name": "survey"})
    r = client.put("/api/schemas/plot/unique-keys", json={"keys": [["site", "number"]]})
    assert r.status_code == 200, r.text


def _add(client: TestClient, site: str, number: int):
    return client.post(
        "/api/collections/survey/records",
        json={"schema_name": "plot", "data": {"site": site, "number": number}},
    )


def test_the_schema_reports_its_keys_by_field_name(client: TestClient) -> None:
    _setup(client)
    assert client.get("/api/schemas/plot").json()["unique_keys"] == [["site", "number"]]


def test_a_duplicate_is_a_422_that_names_the_other_record(client: TestClient) -> None:
    _setup(client)
    assert _add(client, "A", 1).status_code == 201
    refused = _add(client, "A", 1)
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert "same site and number" in detail and "already exists" in detail
    assert _add(client, "A", 2).status_code == 201


def test_a_bad_key_is_refused_with_a_reason(client: TestClient) -> None:
    _setup(client)
    r = client.put("/api/schemas/plot/unique-keys", json={"keys": [["nope"]]})
    assert r.status_code == 404
    r = client.put("/api/schemas/plot/unique-keys", json={"keys": [[]]})
    assert r.status_code == 422


def test_an_empty_list_removes_every_rule(client: TestClient) -> None:
    _setup(client)
    client.put("/api/schemas/plot/unique-keys", json={"keys": []})
    assert _add(client, "A", 1).status_code == 201
    assert _add(client, "A", 1).status_code == 201


def test_the_restore_plan_names_the_record_that_took_its_place(
    client: TestClient,
) -> None:
    _setup(client)
    first = _add(client, "A", 1).json()["id"]
    client.delete(f"/api/records/{first}")
    taker = _add(client, "A", 1).json()["id"]

    plan = client.get(f"/api/records/{first}/restore-plan").json()
    assert plan["can_restore"] is False
    assert plan["blocked_by"] is None
    assert plan["conflict"]["existing_id"] == taker
    assert plan["conflict"]["fields"] == ["site", "number"]
    assert "Change or delete" in plan["blocked"]

    refused = client.post(f"/api/records/{first}/restore")
    assert refused.status_code == 422
    assert "can't come back" in refused.json()["detail"]

    client.delete(f"/api/records/{taker}")
    assert client.get(f"/api/records/{first}/restore-plan").json()["can_restore"]
    assert client.post(f"/api/records/{first}/restore").status_code == 200


def test_restoring_a_selection_leaves_the_clashing_one_and_says_so(
    client: TestClient,
) -> None:
    _setup(client)
    clash = _add(client, "A", 1).json()["id"]
    fine = _add(client, "A", 2).json()["id"]
    client.delete(f"/api/records/{clash}")
    client.delete(f"/api/records/{fine}")
    _add(client, "A", 1)

    r = client.post("/api/records/restore-selected", json={"ids": [clash, fine]}).json()
    assert r["restored"] == 1
    assert r["left"] == 1
