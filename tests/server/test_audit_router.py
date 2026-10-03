from __future__ import annotations

from fastapi.testclient import TestClient


def test_record_audit_lists_create_entry(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/collections", json={"name": "study-2024"})
    create = client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {}},
    )
    record_id = create.json()["id"]

    response = client.get(f"/api/records/{record_id}/audit")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "create"
    assert body["items"][0]["entity_type"] == "record"
    assert body["items"][0]["entity_id"] == record_id


def test_record_audit_reflects_update(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post(
        "/api/schemas/trial/fields", json={"name": "age", "type": "integer"}
    )
    client.post("/api/collections", json={"name": "study-2024"})
    create = client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {"age": 1}},
    )
    record_id = create.json()["id"]
    client.patch(f"/api/records/{record_id}", json={"data": {"age": 2}})

    response = client.get(f"/api/records/{record_id}/audit")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    actions = {item["action"] for item in body["items"]}
    assert actions == {"create", "update"}


def test_record_audit_missing_record_returns_404(client: TestClient) -> None:
    response = client.get("/api/records/00000000-0000-0000-0000-000000000000/audit")
    assert response.status_code == 404


def test_schema_audit_includes_field_changes(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post(
        "/api/schemas/trial/fields", json={"name": "age", "type": "integer"}
    )

    response = client.get("/api/schemas/trial/audit")
    assert response.status_code == 200
    body = response.json()
    # schema created, field created, and the schema's name template set to the
    # first field (see SchemaService.add_field)
    assert body["total"] == 3
    entity_types = {item["entity_type"] for item in body["items"]}
    assert entity_types == {"schema", "field"}


def test_schema_audit_missing_schema_returns_404(client: TestClient) -> None:
    response = client.get("/api/schemas/does-not-exist/audit")
    assert response.status_code == 404


def test_list_audit_filters_by_entity_type(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/collections", json={"name": "study-2024"})
    client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {}},
    )

    response = client.get("/api/audit", params={"entity_type": "record"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_type"] == "record"
