"""HTTP contract for saved analyses (views with a summary) and the Analytics
page."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _study(client: TestClient):
    client.post("/api/schemas", json={"name": "sample"})
    client.post("/api/schemas/sample/fields", json={"name": "site", "type": "string"})
    client.post("/api/schemas/sample/fields", json={"name": "depth", "type": "float"})


def test_a_view_saves_and_answers_its_summary(client: TestClient):
    _study(client)
    made = client.post(
        "/api/schemas/sample/views",
        json={
            "name": "by site",
            "summary": {"group_by": ["site"], "measures": ["count", "mean:depth"]},
        },
    )
    assert made.status_code == 201, made.text
    assert made.json()["summary"]["measures"] == ["count", "mean:depth"]
    bad = client.post(
        "/api/schemas/sample/views",
        json={"name": "bad", "summary": {"group_by": ["nowhere"]}},
    )
    assert bad.status_code == 422
    # Omitted, the summary stays; null clears it.
    kept = client.patch("/api/schemas/sample/views/by site", json={"columns": ["site"]})
    assert kept.json()["summary"] is not None
    cleared = client.patch("/api/schemas/sample/views/by site", json={"summary": None})
    assert cleared.json()["summary"] is None


def test_the_page_is_read_and_replaced_whole(client: TestClient):
    _study(client)
    view = client.post(
        "/api/schemas/sample/views",
        json={"name": "by site", "summary": {"group_by": ["site"]}},
    ).json()
    page = client.get("/api/dashboard").json()
    assert page["edited"] is False
    assert "storage" in page["widgets"]
    cards = [
        {"id": c["id"], "kind": c["kind"], "size": c["size"], "widget": c["widget"]}
        for c in page["cards"]
    ]
    cards.insert(
        0, {"id": "mine", "kind": "analysis", "size": "wide", "view": view["id"]}
    )
    saved = client.put("/api/dashboard", json={"cards": cards[:3]})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["edited"] is True
    assert [c["id"] for c in body["cards"]] == ["mine", cards[1]["id"], cards[2]["id"]]
    assert body["cards"][0]["analysis"]["name"] == "by site"

    refused = client.put(
        "/api/dashboard",
        json={"cards": [{"id": "w", "kind": "widget", "widget": "weather"}]},
    )
    assert refused.status_code == 422
    history = client.get("/api/audit/events", params={"limit": 10}).json()
    assert any(
        (e.get("entry") or {}).get("entity_type") == "dashboard"
        for e in history["items"]
    )
