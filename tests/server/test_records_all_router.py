"""`GET /records/all` and a collection's list with no schema: every kind of
record at once, beneath a record, filtered by open notes; a field filter
refused."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _tree(client: TestClient) -> dict[str, str]:
    client.post("/api/schemas", json={"name": "encounter"})
    client.post(
        "/api/schemas/encounter/fields", json={"name": "site", "type": "string"}
    )
    client.post("/api/schemas", json={"name": "recording", "parent": "encounter"})
    client.post("/api/collections", json={"name": "survey"})
    enc = client.post(
        "/api/collections/survey/records",
        json={"schema_name": "encounter", "data": {"site": "reef"}},
    ).json()["id"]
    rec = client.post(
        "/api/collections/survey/records",
        json={"schema_name": "recording", "data": {}, "parent_record_id": enc},
    )
    assert rec.status_code == 201, rec.text
    return {"encounter": enc, "recording": rec.json()["id"]}


def test_every_kind_is_listed_with_open_notes_on_any(client: TestClient):
    ids = _tree(client)
    everything = client.get("/api/records/all", params={"sort": "@kind"})
    assert everything.status_code == 200, everything.text
    body = everything.json()
    assert body["total"] == 2
    assert [r["schema_name"] for r in body["items"]] == ["encounter", "recording"]

    beneath = client.get(
        "/api/collections/survey/records", params={"within": ids["encounter"]}
    )
    assert [r["id"] for r in beneath.json()["items"]] == [ids["recording"]]

    client.post(f"/api/records/{ids['recording']}/notes", json={"body": "48 kHz?"})
    open_ones = client.get(
        "/api/records/all",
        params={
            "filter": json.dumps({"field": "@open_notes", "op": "eq", "value": True})
        },
    ).json()
    assert [(r["id"], r["latest_note"]) for r in open_ones["items"]] == [
        (ids["recording"], "48 kHz?")
    ]


def test_a_field_filter_needs_a_kind(client: TestClient):
    _tree(client)
    refused = client.get(
        "/api/records/all",
        params={"filter": json.dumps({"field": "site", "op": "eq", "value": "reef"})},
    )
    assert refused.status_code == 422
    assert "choose a kind" in refused.json()["detail"]
    one_kind = client.get(
        "/api/records/all",
        params={
            "schema": "encounter",
            "filter": json.dumps({"field": "site", "op": "eq", "value": "reef"}),
        },
    )
    assert one_kind.json()["total"] == 1
