"""POST /records/summary: the records a query lists, grouped and measured;
the measures each type allows are in GET /schemas/field-types."""

from __future__ import annotations

import csv
import io
import json

from fastapi.testclient import TestClient


def _seed(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "sample"})
    for name, dtype in (("habitat", "string"), ("depth", "float"), ("taken", "date")):
        resp = client.post(
            "/api/schemas/sample/fields", json={"name": name, "type": dtype}
        )
        assert resp.status_code in (200, 201), resp.text
    client.post("/api/collections", json={"name": "survey"})
    for habitat, depth, taken in (
        ("reef", 2.0, "2024-01-03"),
        ("reef", 4.0, "2024-02-10"),
        ("sand", 10.0, "2024-02-11"),
    ):
        resp = client.post(
            "/api/collections/survey/records",
            json={
                "schema_name": "sample",
                "data": {"habitat": habitat, "depth": depth, "taken": taken},
            },
        )
        assert resp.status_code == 201, resp.text


def _summary(client: TestClient, **body):
    return client.post(
        "/api/records/summary",
        json={"collection": "survey", "schema_name": "sample", **body},
    )


def test_groups_and_measures(client: TestClient) -> None:
    _seed(client)
    resp = _summary(client, group_by=["habitat"], measures=["count", "mean:depth"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [c["key"] for c in body["measure_columns"]] == ["count", "mean:depth"]
    assert [(r["groups"][0]["value"], r["values"]) for r in body["rows"]] == [
        ("reef", [2, 3.0]),
        ("sand", [1, 10.0]),
    ]
    assert body["total"] == [3, 16 / 3]
    # Each group's condition lists exactly its records.
    where = body["rows"][0]["where"]
    listed = client.get(
        "/api/collections/survey/records",
        params={"schema": "sample", "filter": json.dumps(where)},
    ).json()
    assert listed["total"] == 2


def test_periods_and_ranges(client: TestClient) -> None:
    _seed(client)
    body = _summary(client, group_by=["taken:month", "depth:5"]).json()
    assert [[g["value"] for g in r["groups"]] for r in body["rows"]] == [
        ["2024-01", 0],
        ["2024-02", 0],
        ["2024-02", 10],
    ]
    first = body["rows"][0]["groups"][0]
    assert (first["lower"], first["upper"]) == ("2024-01-01", "2024-02-01")


def test_a_table_file(client: TestClient) -> None:
    _seed(client)
    resp = client.post(
        "/api/records/summary?format=csv",
        json={
            "collection": "survey",
            "schema_name": "sample",
            "group_by": ["habitat"],
            "measures": ["count", "max:depth"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert "sample-summary.csv" in resp.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows == [
        ["Habitat", "Records", "Largest Depth"],
        ["reef", "2", "4.0"],
        ["sand", "1", "10.0"],
        ["Total", "3", "10.0"],
    ]


def test_refusals(client: TestClient) -> None:
    _seed(client)
    assert _summary(client, measures=["mean:habitat"]).status_code == 422
    assert _summary(client, group_by=["nope"]).status_code == 422
    resp = client.post("/api/records/summary", json={"collection": "survey"})
    assert resp.status_code == 422
    assert _summary(client, collection="missing").status_code == 404
    assert (
        client.post(
            "/api/records/summary?format=pdf", json={"schema_name": "sample"}
        ).status_code
        == 422
    )


def test_every_collection_when_none_is_named(client: TestClient) -> None:
    _seed(client)
    resp = client.post("/api/records/summary", json={"schema_name": "sample"})
    assert resp.status_code == 200 and resp.json()["total"] == [3]


def test_field_types_say_what_each_type_allows(client: TestClient) -> None:
    body = client.get("/api/schemas/field-types").json()
    types = {t["type"]: t for t in body["types"]}
    assert "mean" in types["float"]["measures"]
    assert types["float"]["grouping"] == "bin"
    assert types["date"]["buckets"] == ["year", "month", "week", "day"]
    assert types["geo"]["measures"] == ["filled"] and types["geo"]["grouping"] is None
    assert types["tags"]["grouping"] == "each"
    assert [m["key"] for m in body["summary_measures"]][0] == "count"
