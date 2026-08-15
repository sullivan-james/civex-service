"""HTTP contract for the schema delete-impact endpoint and delete's cascade
to the schema's own records (not to schemas that inherit from it)."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_delete_impact_for_a_schema_with_no_dependents(client: TestClient):
    client.post("/api/schemas", json={"name": "trial"})
    response = client.get("/api/schemas/trial/delete-impact")
    assert response.status_code == 200, response.text
    assert response.json() == {"child_schema_count": 0, "record_count": 0}


def test_delete_impact_counts_child_schemas_and_own_records(client: TestClient):
    client.post("/api/schemas", json={"name": "base"})
    client.post("/api/schemas", json={"name": "derived", "parent": "base"})
    client.post("/api/collections", json={"name": "study"})
    base_record = client.post(
        "/api/collections/study/records", json={"schema_name": "base", "data": {}}
    ).json()
    client.post(
        "/api/collections/study/records",
        json={
            "schema_name": "derived",
            "data": {},
            "parent_record_id": base_record["id"],
        },
    )

    response = client.get("/api/schemas/base/delete-impact")
    assert response.status_code == 200, response.text
    assert response.json() == {"child_schema_count": 1, "record_count": 1}


def test_delete_impact_404s_for_missing_schema(client: TestClient):
    response = client.get("/api/schemas/does-not-exist/delete-impact")
    assert response.status_code == 404


def test_delete_cascades_to_records_over_http(client: TestClient):
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/collections", json={"name": "study"})
    record = client.post(
        "/api/collections/study/records", json={"schema_name": "trial", "data": {}}
    ).json()

    delete_response = client.delete("/api/schemas/trial")
    assert delete_response.status_code == 204, delete_response.text

    assert client.get("/api/schemas/trial").status_code == 404
    assert client.get(f"/api/records/{record['id']}").status_code == 404


def test_delete_leaves_child_schema_and_its_records_over_http(client: TestClient):
    client.post("/api/schemas", json={"name": "base"})
    client.post("/api/schemas", json={"name": "derived", "parent": "base"})
    client.post("/api/collections", json={"name": "study"})
    base_record = client.post(
        "/api/collections/study/records", json={"schema_name": "base", "data": {}}
    ).json()
    derived_record = client.post(
        "/api/collections/study/records",
        json={
            "schema_name": "derived",
            "data": {},
            "parent_record_id": base_record["id"],
        },
    ).json()

    delete_response = client.delete("/api/schemas/base")
    assert delete_response.status_code == 204, delete_response.text

    assert client.get("/api/schemas/base").status_code == 404
    assert client.get("/api/schemas/derived").status_code == 200
    assert client.get(f"/api/records/{base_record['id']}").status_code == 404
    assert client.get(f"/api/records/{derived_record['id']}").status_code == 200
