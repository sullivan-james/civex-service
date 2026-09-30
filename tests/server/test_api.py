from __future__ import annotations

from fastapi.testclient import TestClient


def test_api_schemas_empty(client: TestClient) -> None:
    response = client.get("/api/schemas")
    assert response.status_code == 200
    assert response.json() == []


def test_api_create_schema(client: TestClient) -> None:
    response = client.post("/api/schemas", json={"name": "trial", "description": "A trial schema"})
    assert response.status_code == 201
    assert response.json()["name"] == "trial"

    response = client.get("/api/schemas")
    assert any(s["name"] == "trial" for s in response.json())


def test_api_create_schema_duplicate_name_returns_409(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    response = client.post("/api/schemas", json={"name": "trial"})
    assert response.status_code == 409


def test_api_create_dataset(client: TestClient) -> None:
    response = client.post("/api/collections", json={"name": "study-2024"})
    assert response.status_code == 201
    assert response.json()["name"] == "study-2024"


def test_api_update_record_restriction_violation_returns_422(client: TestClient) -> None:
    """A restriction violation on PATCH must surface as a 422 ValidationError,
    not an unhandled 500 — the frontend maps this detail to a field-level
    message, which only works if the API returns it at all."""
    client.post("/api/schemas", json={"name": "trial"})
    client.post(
        "/api/schemas/trial/fields",
        json={"name": "age", "type": "integer", "restrictions": {"min": 0, "max": 120}},
    )
    client.post("/api/collections", json={"name": "study-2024"})
    create = client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {"age": 30}},
    )
    assert create.status_code == 201
    record_id = create.json()["id"]

    response = client.patch(f"/api/records/{record_id}", json={"data": {"age": 200}})
    assert response.status_code == 422
    assert "age" in response.json()["detail"]


def test_api_update_record_replaces_data_rather_than_merging(client: TestClient) -> None:
    """PATCH replaces a record's data wholesale. The frontend's inline cell
    editing depends on this: it sends the full data dict with one field
    changed (or removed, to clear it), so a change here must be made there too."""
    client.post("/api/schemas", json={"name": "trial"})
    for name, type_ in (("age", "integer"), ("site", "string")):
        client.post("/api/schemas/trial/fields", json={"name": name, "type": type_})
    client.post("/api/collections", json={"name": "study-2024"})
    create = client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {"age": 30, "site": "north"}},
    )
    record_id = create.json()["id"]

    # Full payload with one field changed keeps the rest.
    full = client.patch(f"/api/records/{record_id}", json={"data": {"age": 31, "site": "north"}})
    assert full.status_code == 200
    assert full.json()["data"] == {"age": 31, "site": "north"}

    # Omitting a key clears it; a partial payload does not merge.
    partial = client.patch(f"/api/records/{record_id}", json={"data": {"age": 32}})
    assert partial.status_code == 200
    assert partial.json()["data"] == {"age": 32}
