"""HTTP contract for GET /collections/{name}/export.csv."""
from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient


def _rows(resp) -> list[dict]:
    return list(csv.DictReader(io.StringIO(resp.text)))


def test_export_csv_defaults_to_all_records(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "invoice"})
    client.post(
        "/api/schemas/invoice/fields", json={"name": "amount", "type": "integer"}
    )
    client.post("/api/collections", json={"name": "study"})
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {"amount": 1}},
    )
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {"amount": 2}},
    )

    resp = client.get("/api/collections/study/export.csv")
    assert resp.status_code == 200
    assert len(_rows(resp)) == 2


def test_export_csv_honors_schema_filter(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "invoice"})
    client.post("/api/schemas", json={"name": "receipt"})
    client.post("/api/collections", json={"name": "study"})
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {}},
    )
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "receipt", "data": {}},
    )

    resp = client.get("/api/collections/study/export.csv", params={"schema": "invoice"})
    assert resp.status_code == 200
    rows = _rows(resp)
    assert len(rows) == 1
    assert rows[0]["schema"] == "invoice"


def test_export_csv_honors_search_filter(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "invoice"})
    client.post(
        "/api/schemas/invoice/fields", json={"name": "vendor", "type": "string"}
    )
    client.post("/api/collections", json={"name": "study"})
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {"vendor": "acme"}},
    )
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {"vendor": "other"}},
    )

    resp = client.get("/api/collections/study/export.csv", params={"search": "acme"})
    assert resp.status_code == 200
    rows = _rows(resp)
    assert len(rows) == 1
    assert rows[0]["vendor"] == "acme"


def test_export_csv_honors_where_filter(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "invoice"})
    client.post(
        "/api/schemas/invoice/fields", json={"name": "vendor", "type": "string"}
    )
    client.post("/api/collections", json={"name": "study"})
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {"vendor": "acme"}},
    )
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {"vendor": "other"}},
    )

    resp = client.get(
        "/api/collections/study/export.csv",
        params={"schema": "invoice", "where": "vendor=acme"},
    )
    assert resp.status_code == 200
    rows = _rows(resp)
    assert len(rows) == 1
    assert rows[0]["vendor"] == "acme"


def test_export_csv_unknown_collection_returns_404(client: TestClient) -> None:
    resp = client.get("/api/collections/does-not-exist/export.csv")
    assert resp.status_code == 404


def test_export_csv_invalid_where_filter_returns_422(client: TestClient) -> None:
    client.post("/api/collections", json={"name": "study"})
    resp = client.get(
        "/api/collections/study/export.csv", params={"where": "not-a-filter"}
    )
    assert resp.status_code == 422
