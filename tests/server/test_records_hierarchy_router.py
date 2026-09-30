"""HTTP contract for hierarchy-aware record queries: `within`, qualified
filter leaves, `sort`, `columns`/`derived`, `child_counts`, scoped counts,
ancestors on a single fetch, and filter-scoped bulk delete + export."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


def _post(client: TestClient, url: str, body: dict, status: int = 201):
    resp = client.post(url, json=body)
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture()
def seeded(client: TestClient) -> dict[str, str]:
    _post(client, "/api/schemas", {"name": "encounter"})
    _post(client, "/api/schemas/encounter/fields", {"name": "site", "type": "string"})
    _post(client, "/api/schemas", {"name": "recording", "parent": "encounter"})
    _post(client, "/api/schemas/recording/fields", {"name": "sample_rate", "type": "integer"})
    _post(client, "/api/schemas", {"name": "selection", "parent": "recording"})
    _post(client, "/api/schemas/selection/fields", {"name": "selection_table", "type": "string"})
    _post(client, "/api/collections", {"name": "hb"})

    def add(schema, data, parent=None):
        body = {"schema_name": schema, "data": data}
        if parent:
            body["parent_record_id"] = parent
        return _post(client, "/api/collections/hb/records", body)["id"]

    e1 = add("encounter", {"site": "Stellwagen"})
    r1 = add("recording", {"sample_rate": 96}, e1)
    r2 = add("recording", {"sample_rate": 48}, e1)
    s1 = add("selection", {"selection_table": "a.txt"}, r1)
    s2 = add("selection", {}, r1)
    s3 = add("selection", {}, r2)
    return {"e1": e1, "r1": r1, "r2": r2, "s1": s1, "s2": s2, "s3": s3}


def _list(client, url="/api/collections/hb/records", **params):
    resp = client.get(url, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_within_and_deep_filter(client: TestClient, seeded):
    body = _list(
        client,
        schema="selection",
        within=seeded["e1"],
        filter=json.dumps({"field": "selection_table", "op": "is_null"}),
    )
    assert body["total"] == 2
    assert {r["id"] for r in body["items"]} == {seeded["s2"], seeded["s3"]}


def test_filter_on_descendant_from_the_parent_list(client: TestClient, seeded):
    tree = {"schema": "selection", "field": "selection_table", "op": "is_null"}
    body = _list(client, schema="recording", filter=json.dumps(tree))
    assert {r["id"] for r in body["items"]} == {seeded["r1"], seeded["r2"]}


def test_child_counts_and_derived_columns(client: TestClient, seeded):
    body = _list(
        client,
        schema="recording",
        within=seeded["e1"],
        child_counts="true",
        columns=["site"],
        sort="sample_rate:desc",
    )
    assert [r["id"] for r in body["items"]] == [seeded["r1"], seeded["r2"]]
    assert body["items"][0]["child_counts"] == {"selection": 2}
    assert body["items"][0]["derived"] == {"site": "Stellwagen"}


def test_counts_within_a_record(client: TestClient, seeded):
    resp = client.get(
        "/api/collections/hb/record-counts", params={"within": seeded["e1"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"recording": 2, "selection": 3}


def test_schema_wide_list_isnt_scoped_to_a_collection(client: TestClient, seeded):
    body = _list(client, url="/api/schemas/selection/records")
    assert body["total"] == 3


def test_get_record_returns_its_ancestors(client: TestClient, seeded):
    body = client.get(f"/api/records/{seeded['s1']}").json()
    assert [(a["schema_name"], a["id"]) for a in body["ancestors"]] == [
        ("encounter", seeded["e1"]),
        ("recording", seeded["r1"]),
    ]
    assert client.get(f"/api/records/{seeded['e1']}").json()["ancestors"] == []


def test_bad_query_is_422_not_an_empty_list(client: TestClient, seeded):
    resp = client.get(
        "/api/collections/hb/records",
        params={
            "schema": "selection",
            "filter": json.dumps({"field": "nope", "op": "eq", "value": 1}),
        },
    )
    assert resp.status_code == 422
    assert "Unknown filter field" in resp.json()["detail"]
    assert (
        client.get(
            "/api/collections/hb/records", params={"within": seeded["e1"]}
        ).status_code
        == 422
    )


def test_delete_with_a_filter_deletes_only_what_matches(client: TestClient, seeded):
    resp = client.request(
        "DELETE",
        "/api/collections/hb/records",
        params={
            "schema": "selection",
            "within": seeded["r1"],
            "filter": json.dumps({"field": "selection_table", "op": "is_null"}),
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 1}
    remaining = _list(client, schema="selection")
    assert {r["id"] for r in remaining["items"]} == {seeded["s1"], seeded["s3"]}


def test_export_honours_the_same_filters(client: TestClient, seeded):
    resp = client.get(
        "/api/collections/hb/export.csv",
        params={
            "schema": "selection",
            "filter": json.dumps({"field": "selection_table", "op": "is_null"}),
        },
    )
    assert resp.status_code == 200, resp.text
    lines = resp.text.strip().splitlines()
    assert len(lines) == 3  # header + s2 + s3
