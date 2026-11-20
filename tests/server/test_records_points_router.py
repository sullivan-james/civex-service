"""POST /records/points: where the records a query lists are, for a map."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _seed(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "sample"})
    for name, dtype in (("habitat", "string"), ("where", "geo"), ("depth", "float")):
        resp = client.post(
            "/api/schemas/sample/fields", json={"name": name, "type": dtype}
        )
        assert resp.status_code in (200, 201), resp.text
    client.post("/api/collections", json={"name": "survey"})
    for habitat, where in (
        ("reef", {"type": "Point", "coordinates": [1, 2]}),
        ("reef", {"type": "LineString", "coordinates": [[0, 0], [3, 4]]}),
        ("sand", {"type": "Point", "coordinates": [5, 6]}),
        ("sand", None),
    ):
        resp = client.post(
            "/api/collections/survey/records",
            json={
                "schema_name": "sample",
                "data": {"habitat": habitat, "where": where},
            },
        )
        assert resp.status_code == 201, resp.text


def _points(client: TestClient, **body):
    return client.post(
        "/api/records/points",
        json={"collection": "survey", "schema_name": "sample", **body},
    )


def test_points_of_a_query(client: TestClient) -> None:
    _seed(client)
    resp = _points(client, field="where")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["schema_name"], body["field"], body["total"]) == ("sample", "where", 3)
    assert not body["truncated"]
    assert [(p["name"], p["geometry"]["type"]) for p in body["points"]] == [
        ("reef", "Point"),
        ("reef", "LineString"),
        ("sand", "Point"),
    ]
    filtered = _points(
        client,
        field="where",
        filter={"field": "habitat", "op": "eq", "value": "sand"},
    ).json()
    assert [p["geometry"]["coordinates"] for p in filtered["points"]] == [[5, 6]]


def test_capped(client: TestClient) -> None:
    _seed(client)
    body = _points(client, field="where", limit=1).json()
    assert len(body["points"]) == 1 and body["total"] == 3 and body["truncated"]


def test_refused(client: TestClient) -> None:
    _seed(client)
    assert _points(client, field="depth").status_code == 422
    assert _points(client, field="nope").status_code == 422
    resp = client.post("/api/records/points", json={"field": "where"})
    assert resp.status_code == 422
