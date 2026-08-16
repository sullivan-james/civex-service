"""HTTP contract for the views CRUD API."""

from __future__ import annotations

import io
import zipfile

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


def test_create_view_with_single_hop_join_column_via_api(client: TestClient):
    _make_schema(client, "customer", fields=[("email", "string")])
    _make_schema(client, "invoice", fields=[("amount", "integer")])
    client.post(
        "/api/schemas/invoice/fields",
        json={
            "name": "customer",
            "type": "reference",
            "restrictions": {"schema": "customer"},
        },
    )

    response = client.post(
        "/api/schemas/invoice/views",
        json={"name": "with_customer", "columns": ["amount", "customer.email"]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["columns"] == ["amount", "customer.email"]


def test_preview_view_via_api(client: TestClient):
    _make_schema(client, "trial", fields=[("subject", "string"), ("age", "integer")])
    client.post("/api/collections", json={"name": "study"})
    for data in [
        {"subject": "s1", "age": 10},
        {"subject": "s2", "age": 20},
    ]:
        resp = client.post(
            "/api/collections/study/records",
            json={"schema_name": "trial", "data": data},
        )
        assert resp.status_code == 201, resp.text

    response = client.post(
        "/api/schemas/trial/views/preview",
        json={
            "columns": ["subject", "age"],
            "filter_tree": {"field": "age", "op": "gte", "value": 15},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["rows"] == [{"subject": "s2", "age": 20}]


def test_preview_view_on_missing_schema_returns_404(client: TestClient):
    response = client.post("/api/schemas/missing/views/preview", json={})
    assert response.status_code == 404


def test_preview_view_with_unknown_column_returns_422(client: TestClient):
    _make_schema(client, "trial")
    response = client.post(
        "/api/schemas/trial/views/preview", json={"columns": ["nope"]}
    )
    assert response.status_code == 422


def test_create_view_with_multi_hop_join_column_returns_422(client: TestClient):
    _make_schema(client, "customer", fields=[("email", "string")])
    _make_schema(client, "invoice")
    client.post(
        "/api/schemas/invoice/fields",
        json={
            "name": "customer",
            "type": "reference",
            "restrictions": {"schema": "customer"},
        },
    )

    response = client.post(
        "/api/schemas/invoice/views",
        json={"name": "bad", "columns": ["customer.region.name"]},
    )
    assert response.status_code == 422


def _upload(client: TestClient, filename: str, content: bytes) -> dict:
    resp = client.post(
        "/api/files", files={"file": (filename, io.BytesIO(content), "text/plain")}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_export_view_csv_flattens_joined_columns(client: TestClient):
    _make_schema(client, "customer", fields=[("email", "string")])
    _make_schema(client, "invoice", fields=[("amount", "integer")])
    client.post(
        "/api/schemas/invoice/fields",
        json={
            "name": "customer",
            "type": "reference",
            "restrictions": {"schema": "customer"},
        },
    )
    client.post("/api/collections", json={"name": "study"})
    customer = client.post(
        "/api/collections/study/records",
        json={"schema_name": "customer", "data": {"email": "a@example.com"}},
    ).json()
    client.post(
        "/api/collections/study/records",
        json={
            "schema_name": "invoice",
            "data": {"amount": 100, "customer": customer["id"]},
        },
    )
    client.post(
        "/api/schemas/invoice/views",
        json={"name": "with_customer", "columns": ["amount", "customer.email"]},
    )

    resp = client.get("/api/schemas/invoice/views/with_customer/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.text.splitlines() == [
        "amount,customer.email",
        "100,a@example.com",
    ]


def test_export_view_json_nests_joined_columns(client: TestClient):
    _make_schema(client, "customer", fields=[("email", "string")])
    _make_schema(client, "invoice", fields=[("amount", "integer")])
    client.post(
        "/api/schemas/invoice/fields",
        json={
            "name": "customer",
            "type": "reference",
            "restrictions": {"schema": "customer"},
        },
    )
    client.post("/api/collections", json={"name": "study"})
    customer = client.post(
        "/api/collections/study/records",
        json={"schema_name": "customer", "data": {"email": "a@example.com"}},
    ).json()
    client.post(
        "/api/collections/study/records",
        json={
            "schema_name": "invoice",
            "data": {"amount": 100, "customer": customer["id"]},
        },
    )
    client.post(
        "/api/schemas/invoice/views",
        json={"name": "with_customer", "columns": ["amount", "customer.email"]},
    )

    resp = client.get(
        "/api/schemas/invoice/views/with_customer/export", params={"format": "json"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == [{"amount": 100, "customer": {"email": "a@example.com"}}]


def test_export_view_bundles_file_columns_as_zip(client: TestClient):
    _make_schema(client, "invoice", fields=[("scan", "file")])
    client.post("/api/collections", json={"name": "study"})
    scan = _upload(client, "scan.pdf", b"scan-bytes")
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {"scan": scan}},
    )
    client.post(
        "/api/schemas/invoice/views",
        json={"name": "with_scan", "columns": ["scan"]},
    )

    resp = client.get("/api/schemas/invoice/views/with_scan/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    assert "with_scan.csv" in names
    file_entries = [n for n in names if n != "with_scan.csv"]
    assert len(file_entries) == 1
    assert file_entries[0].endswith("/scan.pdf")
    assert zf.read(file_entries[0]) == b"scan-bytes"
    assert zf.read("with_scan.csv").decode().splitlines() == [
        "scan",
        "scan.pdf",
    ]


def test_export_view_invalid_format_returns_422(client: TestClient):
    _make_schema(client, "trial")
    client.post("/api/schemas/trial/views", json={"name": "view1"})

    resp = client.get(
        "/api/schemas/trial/views/view1/export", params={"format": "xml"}
    )
    assert resp.status_code == 422


def test_export_missing_view_returns_404(client: TestClient):
    _make_schema(client, "trial")
    resp = client.get("/api/schemas/trial/views/missing/export")
    assert resp.status_code == 404
