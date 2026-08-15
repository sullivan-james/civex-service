"""HTTP contract for the multi-operator `filter` query param on
GET /collections/{name}/records, alongside the pre-existing simple `where=`
equality form."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _seed(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "employee"})
    for name, dtype in [("name", "string"), ("age", "integer"), ("dept", "string")]:
        client.post(
            "/api/schemas/employee/fields", json={"name": name, "type": dtype}
        )
    client.post("/api/collections", json={"name": "acme"})
    for data in [
        {"name": "Alice", "age": 30, "dept": "eng"},
        {"name": "Bob", "age": 25, "dept": "sales"},
        {"name": "Carol", "age": 40, "dept": "eng"},
    ]:
        resp = client.post(
            "/api/collections/acme/records",
            json={"schema_name": "employee", "data": data},
        )
        assert resp.status_code == 201, resp.text


def test_filter_query_param_and_group(client: TestClient) -> None:
    _seed(client)
    tree = {
        "and": [
            {"field": "dept", "op": "eq", "value": "eng"},
            {"field": "age", "op": "gte", "value": 30},
        ]
    }
    resp = client.get(
        "/api/collections/acme/records",
        params={"schema": "employee", "filter": json.dumps(tree)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert {r["data"]["name"] for r in body["items"]} == {"Alice", "Carol"}


def test_filter_combines_with_legacy_where(client: TestClient) -> None:
    _seed(client)
    resp = client.get(
        "/api/collections/acme/records",
        params={
            "schema": "employee",
            "where": "dept=eng",
            "filter": json.dumps({"field": "age", "op": "gt", "value": 35}),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {r["data"]["name"] for r in body["items"]} == {"Carol"}


def test_filter_invalid_json_is_422(client: TestClient) -> None:
    _seed(client)
    resp = client.get(
        "/api/collections/acme/records",
        params={"schema": "employee", "filter": "{not json"},
    )
    assert resp.status_code == 422


def test_filter_unknown_operator_is_422(client: TestClient) -> None:
    _seed(client)
    resp = client.get(
        "/api/collections/acme/records",
        params={
            "schema": "employee",
            "filter": json.dumps({"field": "age", "op": "startswith", "value": "3"}),
        },
    )
    assert resp.status_code == 422


def test_where_still_works_without_filter(client: TestClient) -> None:
    _seed(client)
    resp = client.get(
        "/api/collections/acme/records",
        params={"schema": "employee", "where": "dept=sales"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {r["data"]["name"] for r in body["items"]} == {"Bob"}
