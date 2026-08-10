"""HTTP contract for soft-delete/restore/purge on schemas, collections and
records, and the retention setting that governs purge eligibility.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_retention_settings_round_trip(client: TestClient) -> None:
    resp = client.get("/api/settings/retention")
    assert resp.status_code == 200
    assert resp.json() == {"purge_after_days": 30}

    patch_resp = client.patch("/api/settings/retention", json={"purge_after_days": 7})
    assert patch_resp.status_code == 200
    assert patch_resp.json() == {"purge_after_days": 7}
    assert client.get("/api/settings/retention").json() == {"purge_after_days": 7}


def test_schema_delete_restore_purge_round_trip(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "animal"})

    delete_resp = client.delete("/api/schemas/animal")
    assert delete_resp.status_code == 204
    assert client.get("/api/schemas/animal").status_code == 404
    assert [s["name"] for s in client.get("/api/schemas").json()] == []
    assert [s["name"] for s in client.get("/api/schemas/deleted").json()] == ["animal"]

    restore_resp = client.post("/api/schemas/animal/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["deleted_at"] is None
    assert client.get("/api/schemas/animal").status_code == 200

    client.delete("/api/schemas/animal")
    purge_resp = client.delete("/api/schemas/animal/purge")
    assert purge_resp.status_code == 204
    assert client.get("/api/schemas/deleted").json() == []


def test_purge_before_delete_is_rejected(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "animal"})
    resp = client.delete("/api/schemas/animal/purge")
    assert resp.status_code == 422


def test_collection_delete_cascades_to_records_and_restore_undoes_it(
    client: TestClient,
) -> None:
    client.post("/api/schemas", json={"name": "animal"})
    client.post("/api/collections", json={"name": "zoo"})
    record_resp = client.post(
        "/api/collections/zoo/records", json={"schema_name": "animal", "data": {}}
    )
    record_id = record_resp.json()["id"]

    assert client.delete("/api/collections/zoo").status_code == 204
    assert client.get("/api/collections/zoo/records").status_code == 404
    deleted_records = client.get("/api/records/deleted").json()
    assert [r["id"] for r in deleted_records] == [record_id]

    restore_resp = client.post("/api/collections/zoo/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["record_count"] == 1
    listed = client.get("/api/collections/zoo/records").json()
    assert [r["id"] for r in listed["items"]] == [record_id]


def test_record_delete_restore_purge_round_trip(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "animal"})
    client.post("/api/collections", json={"name": "zoo"})
    record_id = client.post(
        "/api/collections/zoo/records", json={"schema_name": "animal", "data": {}}
    ).json()["id"]

    assert client.delete(f"/api/records/{record_id}").status_code == 204
    assert client.get(f"/api/records/{record_id}").status_code == 404
    assert [r["id"] for r in client.get("/api/records/deleted").json()] == [record_id]

    restore_resp = client.post(f"/api/records/{record_id}/restore")
    assert restore_resp.status_code == 200
    assert client.get(f"/api/records/{record_id}").status_code == 200

    client.delete(f"/api/records/{record_id}")
    assert client.delete(f"/api/records/{record_id}/purge").status_code == 204
    assert client.get("/api/records/deleted").json() == []


def test_deleted_records_can_be_filtered_by_dataset(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "animal"})
    client.post("/api/collections", json={"name": "zoo"})
    client.post("/api/collections", json={"name": "aquarium"})
    zoo_id = client.post(
        "/api/collections/zoo/records", json={"schema_name": "animal", "data": {}}
    ).json()["id"]
    aquarium_id = client.post(
        "/api/collections/aquarium/records",
        json={"schema_name": "animal", "data": {}},
    ).json()["id"]
    client.delete(f"/api/records/{zoo_id}")
    client.delete(f"/api/records/{aquarium_id}")

    scoped = client.get("/api/records/deleted", params={"dataset": "zoo"}).json()
    assert [r["id"] for r in scoped] == [zoo_id]

    unscoped = client.get("/api/records/deleted").json()
    assert {r["id"] for r in unscoped} == {zoo_id, aquarium_id}
