from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _f(field: str, value: str, op: str = "eq") -> str:
    return json.dumps({"field": field, "op": op, "value": value})


def test_record_audit_lists_create_entry(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/collections", json={"name": "study-2024"})
    create = client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {}},
    )
    record_id = create.json()["id"]

    response = client.get(f"/api/records/{record_id}/audit")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "create"
    assert body["items"][0]["entity_type"] == "record"
    assert body["items"][0]["entity_id"] == record_id


def test_record_audit_reflects_update(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/schemas/trial/fields", json={"name": "age", "type": "integer"})
    client.post("/api/collections", json={"name": "study-2024"})
    create = client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {"age": 1}},
    )
    record_id = create.json()["id"]
    client.patch(f"/api/records/{record_id}", json={"data": {"age": 2}})

    response = client.get(f"/api/records/{record_id}/audit")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    actions = {item["action"] for item in body["items"]}
    assert actions == {"create", "update"}


def test_record_audit_missing_record_returns_404(client: TestClient) -> None:
    response = client.get("/api/records/00000000-0000-0000-0000-000000000000/audit")
    assert response.status_code == 404


def test_schema_audit_includes_field_changes(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/schemas/trial/fields", json={"name": "age", "type": "integer"})

    response = client.get("/api/schemas/trial/audit")
    assert response.status_code == 200
    body = response.json()
    # schema created, field created, and the schema's name template set to the
    # first field (see SchemaService.add_field)
    assert body["total"] == 3
    entity_types = {item["entity_type"] for item in body["items"]}
    assert entity_types == {"schema", "field"}


def test_schema_audit_missing_schema_returns_404(client: TestClient) -> None:
    response = client.get("/api/schemas/does-not-exist/audit")
    assert response.status_code == 404


def test_list_audit_filters_by_entity_type(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/collections", json={"name": "study-2024"})
    client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {}},
    )

    response = client.get("/api/audit", params={"entity_type": "record"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_type"] == "record"


def test_audit_can_be_filtered_by_action_and_sorted(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/collections", json={"name": "study-2024", "description": None})
    record_id = client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {}},
    ).json()["id"]
    client.patch(f"/api/records/{record_id}", json={"data": {}})

    updates = client.get(
        f"/api/records/{record_id}/audit", params={"action": "update"}
    ).json()
    assert updates["total"] == len(updates["items"]) >= 1
    assert {i["action"] for i in updates["items"]} == {"update"}

    oldest_first = client.get(
        f"/api/records/{record_id}/audit", params={"sort": "timestamp:asc"}
    ).json()["items"]
    stamps = [i["timestamp"] for i in oldest_first]
    assert stamps == sorted(stamps)


def _record_with_age(client: TestClient, age: int = 1) -> str:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/schemas/trial/fields", json={"name": "age", "type": "integer"})
    client.post("/api/collections", json={"name": "study-2024"})
    create = client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {"age": age}},
    )
    return create.json()["id"]


def _latest_update(client: TestClient, record_id: str) -> dict:
    items = client.get(f"/api/records/{record_id}/audit").json()["items"]
    return next(i for i in items if i["action"] == "update")


def test_audit_entries_carry_their_changes(client: TestClient) -> None:
    record_id = _record_with_age(client)
    client.patch(f"/api/records/{record_id}", json={"data": {"age": 2}})

    entry = _latest_update(client, record_id)
    assert entry["changes"] == [
        {"field": "age", "label": "Age", "dtype": "integer", "before": 1, "after": 2}
    ]
    single = client.get(f"/api/audit/{entry['id']}")
    assert single.status_code == 200
    assert single.json()["changes"] == entry["changes"]


def test_unknown_audit_entry_is_404(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/audit/{missing}").status_code == 404
    assert client.get("/api/audit/not-an-id").status_code == 400


def test_revert_preview_then_apply(client: TestClient) -> None:
    record_id = _record_with_age(client)
    client.patch(f"/api/records/{record_id}", json={"data": {"age": 2}})
    entry = _latest_update(client, record_id)

    preview = client.get(f"/api/audit/{entry['id']}/revert").json()
    assert preview["kind"] == "update"
    assert preview["can_apply"] is True
    assert preview["fields"][0]["status"] == "apply"
    assert client.get(f"/api/records/{record_id}").json()["data"]["age"] == 2

    done = client.post(f"/api/audit/{entry['id']}/revert", json={})
    assert done.status_code == 200
    assert done.json()["applied"] == ["age"]
    assert client.get(f"/api/records/{record_id}").json()["data"]["age"] == 1


def test_revert_of_an_edited_field_needs_force(client: TestClient) -> None:
    record_id = _record_with_age(client)
    client.patch(f"/api/records/{record_id}", json={"data": {"age": 2}})
    entry = _latest_update(client, record_id)
    client.patch(f"/api/records/{record_id}", json={"data": {"age": 7}})

    preview = client.get(f"/api/audit/{entry['id']}/revert").json()
    assert preview["has_conflicts"] is True

    refused = client.post(f"/api/audit/{entry['id']}/revert", json={})
    assert refused.status_code == 422
    forced = client.post(f"/api/audit/{entry['id']}/revert", json={"force": True})
    assert forced.status_code == 200
    assert client.get(f"/api/records/{record_id}").json()["data"]["age"] == 1


def test_global_feed_filters_by_type_and_how_far_back(client: TestClient) -> None:
    _record_with_age(client)

    everything = client.get("/api/audit").json()
    kinds = {i["entity_type"] for i in everything["items"]}
    assert {"record", "schema", "field", "dataset"} <= kinds

    records = client.get("/api/audit?entity_type=record").json()
    assert records["total"] >= 1
    assert {i["entity_type"] for i in records["items"]} == {"record"}

    future = client.get("/api/audit?since=2999-01-01T00:00:00Z").json()
    assert future["total"] == 0
    past = client.get("/api/audit?since=2000-01-01T00:00:00").json()
    assert past["total"] == everything["total"]


def _create(client: TestClient, headers: dict | None = None) -> str:
    r = client.post(
        "/api/collections/study-2024/records",
        json={"schema_name": "trial", "data": {"age": 1}},
        headers=headers or {},
    )
    return r.json()["id"]


def _project(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/schemas/trial/fields", json={"name": "age", "type": "integer"})
    client.post("/api/collections", json={"name": "study-2024"})


def test_an_import_over_many_requests_is_one_event(client: TestClient) -> None:
    _project(client)
    batch = client.post(
        "/api/audit/batches", json={"kind": "import", "label": "people.csv"}
    ).json()
    header = {"X-Civex-Batch": batch["id"]}
    ids = [_create(client, header) for _ in range(3)]
    _create(client)  # a request without the header is its own event

    events = client.get(
        "/api/audit/events", params={"filter": _f("kind", "record")}
    ).json()
    kinds = [e["kind"] for e in events["items"]]
    assert kinds.count("batch") == 1 and kinds.count("entry") == 1
    imported = next(e for e in events["items"] if e["kind"] == "batch")
    assert imported["count"] == 3
    assert imported["batch"]["label"] == "people.csv"
    assert imported["parts"] == [
        {"entity_type": "record", "action": "create", "count": 3}
    ]

    members = client.get(f"/api/audit/batches/{batch['id']}/entries").json()
    assert members["total"] == 3
    assert {m["entity_id"] for m in members["items"]} == set(ids)
    summary = client.get(f"/api/audit/batches/{batch['id']}").json()
    assert (summary["kind"], summary["count"]) == ("batch", 3)


def test_an_unknown_or_malformed_batch_header_is_ignored(client: TestClient) -> None:
    _project(client)
    _create(client, {"X-Civex-Batch": "00000000-0000-0000-0000-000000000000"})
    _create(client, {"X-Civex-Batch": "not-a-uuid"})
    events = client.get(
        "/api/audit/events", params={"filter": _f("kind", "record")}
    ).json()
    assert [e["kind"] for e in events["items"]] == ["entry", "entry"]


def test_events_filter_by_kind_and_search(client: TestClient) -> None:
    _project(client)
    batch = client.post(
        "/api/audit/batches", json={"kind": "import", "label": "people.csv"}
    ).json()
    _create(client, {"X-Civex-Batch": batch["id"]})
    _create(client)

    def total(**params) -> int:
        return client.get("/api/audit/events", params=params).json()["total"]

    assert total(filter=_f("how", "import")) == 1
    both = json.dumps(
        {
            "and": [
                {"field": "how", "op": "eq", "value": "single"},
                {"field": "kind", "op": "eq", "value": "record"},
            ]
        }
    )
    assert total(filter=both) == 1
    assert total(q="people.csv") == 1
    assert total(q="zzz") == 0
    assert client.get("/api/audit/events?limit=0").status_code == 422
    assert (
        client.get("/api/audit/events", params={"filter": "{nope"}).status_code == 422
    )
    fields = client.get("/api/audit/filter-fields").json()
    assert {f["name"] for f in fields} >= {
        "when",
        "kind",
        "change",
        "how",
        "collection",
        "schema",
        "under",
        "now",
    }


def test_unknown_batch_is_404_and_only_imports_can_be_opened(
    client: TestClient,
) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/audit/batches/{missing}").status_code == 404
    assert client.post("/api/audit/batches", json={"kind": "delete"}).status_code == 422
