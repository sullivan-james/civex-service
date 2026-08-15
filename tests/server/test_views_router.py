"""HTTP contract for the views CRUD API."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _make_schema(client: TestClient, name: str, fields=()):
    client.post("/api/schemas", json={"name": name})
    for field_name, dtype in fields:
        client.post(
            f"/api/schemas/{name}/fields", json={"name": field_name, "type": dtype}
        )


def test_list_views_empty(client: TestClient):
    _make_schema(client, "trial")
    response = client.get("/api/schemas/trial/views")
    assert response.status_code == 200
    assert response.json() == []


def test_create_view_via_api(client: TestClient):
    _make_schema(client, "trial", fields=[("subject", "string"), ("status", "string")])

    response = client.post(
        "/api/schemas/trial/views",
        json={
            "name": "active",
            "columns": ["subject", "status"],
            "filter_tree": {"field": "status", "op": "eq", "value": "active"},
            "sort": [{"field": "subject", "direction": "asc"}],
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "active"
    assert data["schema_name"] == "trial"
    assert data["columns"] == ["subject", "status"]
    assert data["filter_tree"] == {"field": "status", "op": "eq", "value": "active"}
    assert data["sort"] == [{"field": "subject", "direction": "asc"}]


def test_create_view_on_missing_schema_returns_404(client: TestClient):
    response = client.post("/api/schemas/missing/views", json={"name": "view1"})
    assert response.status_code == 404


def test_create_view_with_unknown_column_returns_422(client: TestClient):
    _make_schema(client, "trial")
    response = client.post(
        "/api/schemas/trial/views", json={"name": "bad", "columns": ["nope"]}
    )
    assert response.status_code == 422


def test_create_duplicate_view_returns_409(client: TestClient):
    _make_schema(client, "trial")
    client.post("/api/schemas/trial/views", json={"name": "view1"})
    response = client.post("/api/schemas/trial/views", json={"name": "view1"})
    assert response.status_code == 409


def test_get_view(client: TestClient):
    _make_schema(client, "trial")
    client.post("/api/schemas/trial/views", json={"name": "view1"})

    response = client.get("/api/schemas/trial/views/view1")
    assert response.status_code == 200
    assert response.json()["name"] == "view1"


def test_get_missing_view_returns_404(client: TestClient):
    _make_schema(client, "trial")
    response = client.get("/api/schemas/trial/views/missing")
    assert response.status_code == 404


def test_update_view_via_api(client: TestClient):
    _make_schema(client, "trial", fields=[("subject", "string")])
    client.post(
        "/api/schemas/trial/views", json={"name": "view1", "columns": ["subject"]}
    )

    response = client.patch(
        "/api/schemas/trial/views/view1",
        json={"rename": "view1_renamed", "columns": []},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["name"] == "view1_renamed"
    assert data["columns"] == []


def test_update_view_omitting_columns_key_leaves_it_unchanged(client: TestClient):
    _make_schema(client, "trial", fields=[("subject", "string")])
    client.post(
        "/api/schemas/trial/views", json={"name": "view1", "columns": ["subject"]}
    )

    response = client.patch("/api/schemas/trial/views/view1", json={})
    assert response.status_code == 200, response.text
    assert response.json()["columns"] == ["subject"]


def test_delete_view_via_api(client: TestClient):
    _make_schema(client, "trial")
    client.post("/api/schemas/trial/views", json={"name": "view1"})

    response = client.delete("/api/schemas/trial/views/view1")
    assert response.status_code == 204

    assert client.get("/api/schemas/trial/views/view1").status_code == 404
