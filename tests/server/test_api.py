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
