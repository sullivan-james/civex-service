"""POST /api/records/labels: names for a batch of ids, as they are now."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _setup(client: TestClient) -> list[str]:
    client.post("/api/schemas", json={"name": "sel", "description": None})
    client.post(
        "/api/schemas/sel/fields",
        json={"name": "number", "type": "integer", "required": False},
    )
    client.patch("/api/schemas/sel", json={"display_template": "{schema} {number}"})
    client.post("/api/collections", json={"name": "study", "description": None})
    ids = []
    for n in (1, 2):
        r = client.post(
            "/api/collections/study/records",
            json={"schema_name": "sel", "data": {"number": n}},
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return ids


def test_names_for_a_batch_of_ids(client: TestClient) -> None:
    a, b = _setup(client)

    resp = client.post("/api/records/labels", json={"ids": [a, b, "nonsense"]})

    assert resp.status_code == 200
    by_id = {r["id"]: r for r in resp.json()}
    assert set(by_id) == {a, b}  # the one that isn't a record is left out
    assert by_id[a]["natural_name"] == "sel 1" and by_id[a]["schema_name"] == "sel"
    assert by_id[b]["natural_name"] == "sel 2" and by_id[b]["deleted"] is False


def test_the_name_follows_a_rename_and_a_deletion_is_flagged(
    client: TestClient,
) -> None:
    a, _ = _setup(client)
    client.patch(f"/api/records/{a}", json={"data": {"number": 41}})
    assert (
        client.post("/api/records/labels", json={"ids": [a]}).json()[0]["natural_name"]
        == "sel 41"
    )

    client.delete(f"/api/records/{a}")

    (gone,) = client.post("/api/records/labels", json={"ids": [a]}).json()
    assert gone["deleted"] is True and gone["natural_name"] == "sel 41"


def test_an_empty_batch_and_an_oversized_one(client: TestClient) -> None:
    assert client.post("/api/records/labels", json={"ids": []}).json() == []
    too_many = client.post("/api/records/labels", json={"ids": ["x"] * 201})
    assert too_many.status_code == 422
