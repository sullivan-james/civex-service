"""GET /records/{id}/referrers -- the record page's "Referenced by" counts."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _post(client: TestClient, url: str, body: dict) -> dict:
    resp = client.post(url, json=body)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def test_referrers_grouped_per_collection_schema_and_field(client: TestClient) -> None:
    _post(client, "/api/schemas", {"name": "patient"})
    _post(client, "/api/schemas", {"name": "visit"})
    _post(
        client,
        "/api/schemas/visit/fields",
        {"name": "patient_ref", "type": "reference"},
    )
    _post(client, "/api/collections", {"name": "study"})
    patient = _post(
        client,
        "/api/collections/study/records",
        {"schema_name": "patient", "data": {}},
    )
    for _ in range(2):
        _post(
            client,
            "/api/collections/study/records",
            {"schema_name": "visit", "data": {"patient_ref": patient["id"]}},
        )

    resp = client.get(f"/api/records/{patient['id']}/referrers")

    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {
            "dataset_id": patient["dataset_id"],
            "collection": "study",
            "schema_name": "visit",
            "field_name": "patient_ref",
            "dtype": "reference",
            "count": 2,
        }
    ]


def test_referrers_empty_and_unknown_record(client: TestClient) -> None:
    _post(client, "/api/schemas", {"name": "patient"})
    _post(client, "/api/collections", {"name": "study"})
    patient = _post(
        client,
        "/api/collections/study/records",
        {"schema_name": "patient", "data": {}},
    )

    assert client.get(f"/api/records/{patient['id']}/referrers").json() == []
    missing = client.get("/api/records/00000000-0000-0000-0000-000000000000/referrers")
    assert missing.status_code == 404
