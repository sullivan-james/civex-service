"""POST /records/quality (what needs a look in the records a query lists),
POST /records/quality/records (the records with one issue) and
POST /schemas/{s}/fields/{f}/check (what a rule would make of stored values)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _seed(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "sample"})
    resp = client.post(
        "/api/schemas/sample/fields",
        json={"name": "depth", "type": "integer", "restrictions": {"max": 100}},
    )
    assert resp.status_code in (200, 201), resp.text
    client.post("/api/schemas/sample/fields", json={"name": "note", "type": "string"})
    client.post("/api/collections", json={"name": "survey"})
    for depth in (10, 40, 80):
        resp = client.post(
            "/api/collections/survey/records",
            json={"schema_name": "sample", "data": {"depth": depth}},
        )
        assert resp.status_code == 201, resp.text


def test_a_check_reports_what_a_tightened_rule_left(client: TestClient):
    _seed(client)
    plan = client.post(
        "/api/schemas/sample/fields/depth/check",
        json={"restrictions": {"max": 30}},
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["breaks_rule"] == 2
    assert len(plan.json()["examples"]) == 2

    client.patch("/api/schemas/sample/fields/depth", json={"restrictions": {"max": 30}})
    resp = client.post(
        "/api/records/quality", json={"collection": "survey", "schema_name": "sample"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["records"], body["records_with_issues"]) == (3, 2)
    assert [i["name"] for i in body["issues"]][0] == "breaks_rule"
    (kind,) = body["kinds"]
    (line,) = kind["issues"]
    assert (line["issue"], line["field"], line["count"]) == ("breaks_rule", "depth", 2)
    assert line["filter"] is None
    note = next(b for b in kind["blanks"] if b["field"] == "note")
    assert note["blank"] == 3 and note["filter"]["or"]

    page = client.post(
        "/api/records/quality/records",
        json={
            "collection": "survey",
            "schema_name": "sample",
            "issue": "breaks_rule",
            "field": "depth",
            "limit": 1,
        },
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1
    assert "exceeds maximum" in page.json()["items"][0]["message"]


def test_bad_requests(client: TestClient):
    _seed(client)
    assert (
        client.post(
            "/api/records/quality/records",
            json={"collection": "survey", "issue": "outlier"},
        ).status_code
        == 422
    )
    assert (
        client.post("/api/records/quality", json={"collection": "nowhere"}).status_code
        == 404
    )
    assert (
        client.post("/api/schemas/sample/fields/nope/check", json={}).status_code == 404
    )
    assert (
        client.post(
            "/api/schemas/sample/fields/depth/check",
            json={"restrictions": {"choices": [1]}},
        ).status_code
        == 422
    )
