from __future__ import annotations

from fastapi.testclient import TestClient


def _setup(client: TestClient) -> list[str]:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/collections", json={"name": "study", "schemas": ["trial"]})
    ids = []
    for _ in range(3):
        r = client.post(
            "/api/collections/study/records",
            json={"schema_name": "trial", "data": {}},
        )
        ids.append(r.json()["id"])
    return ids


def test_a_record_in_a_deleted_collection_is_blocked_and_says_by_what(
    client: TestClient,
) -> None:
    ids = _setup(client)
    client.delete("/api/collections/study")

    plan = client.get(f"/api/records/{ids[0]}/restore-plan").json()
    assert plan["can_restore"] is False
    assert plan["blocked_by"]["kind"] == "collection"
    assert plan["blocked_by"]["name"] == "study"

    refused = client.post(f"/api/records/{ids[0]}/restore")
    assert refused.status_code == 422
    assert "collection 'study', which is deleted" in refused.json()["detail"]


def test_a_free_record_plan_names_where_it_goes(client: TestClient) -> None:
    ids = _setup(client)
    client.delete(f"/api/records/{ids[0]}")
    plan = client.get(f"/api/records/{ids[0]}/restore-plan").json()
    assert plan["can_restore"] is True
    assert (plan["records"], plan["collection"]) == (1, "study")
    assert client.post(f"/api/records/{ids[0]}/restore").status_code == 200


def test_collection_and_schema_plans_count_only_what_was_deleted_with_them(
    client: TestClient,
) -> None:
    ids = _setup(client)
    client.delete(f"/api/records/{ids[0]}")  # on its own, first
    client.delete("/api/collections/study")
    plan = client.get("/api/collections/study/restore-plan").json()
    assert (plan["kind"], plan["records"]) == ("collection", 2)
    client.post("/api/collections/study/restore")

    client.delete("/api/schemas/trial")
    plan = client.get("/api/schemas/trial/restore-plan").json()
    assert (plan["kind"], plan["records"]) == ("schema", 2)


def test_plan_of_something_not_deleted_is_422(client: TestClient) -> None:
    ids = _setup(client)
    assert client.get(f"/api/records/{ids[0]}/restore-plan").status_code == 422
    assert client.get("/api/collections/nope/restore-plan").status_code == 404


def test_restore_all_previews_then_restores_what_a_filter_matches(
    client: TestClient,
) -> None:
    ids = _setup(client)
    client.post("/api/records/bulk-delete", json={"ids": ids[:2]})

    plan = client.get("/api/audit/restore-all").json()
    assert (plan["records"], plan["restores"], plan["blocked"]) == (2, 2, 0)

    done = client.post("/api/audit/restore-all", json={"filter": None, "q": None})
    assert done.status_code == 200
    assert (done.json()["restored"], done.json()["records"]) == (2, 2)
    assert client.get("/api/audit/restore-all").json()["things"] == 0
    # What was restored is one event in history.
    events = client.get(
        "/api/audit/events",
        params={"filter": '{"field":"how","op":"eq","value":"restore"}'},
    ).json()
    assert events["total"] == 1


def test_restore_all_can_be_narrowed_by_a_filter(client: TestClient) -> None:
    ids = _setup(client)
    client.post("/api/records/bulk-delete", json={"ids": ids})
    only_other = '{"field":"collection","op":"eq","value":"nope"}'
    assert (
        client.get("/api/audit/restore-all", params={"filter": only_other}).status_code
        == 404
    )
    mine = '{"field":"collection","op":"eq","value":"study"}'
    assert (
        client.get("/api/audit/restore-all", params={"filter": mine}).json()["things"]
        == 3
    )
