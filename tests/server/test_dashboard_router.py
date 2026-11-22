"""HTTP contract for a kind's charts and the Analytics page."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _study(client: TestClient) -> str:
    made = client.post("/api/schemas", json={"name": "sample"}).json()
    client.post("/api/schemas/sample/fields", json={"name": "site", "type": "string"})
    client.post("/api/schemas/sample/fields", json={"name": "depth", "type": "float"})
    client.post("/api/schemas/sample/fields", json={"name": "spot", "type": "geo"})
    return made["id"]


def test_a_kind_keeps_its_charts(client: TestClient):
    _study(client)
    charts = [
        {"id": "a", "title": "Per site", "group_by": ["site"], "measures": ["count"]},
        {"id": "b", "map": "spot"},
    ]
    saved = client.put("/api/schemas/sample/charts", json={"charts": charts})
    assert saved.status_code == 200, saved.text
    got = client.get("/api/schemas/sample").json()["charts"]
    assert [c["id"] for c in got] == ["a", "b"]
    assert got[0]["group_by"] == ["site"] and got[0]["title"] == "Per site"
    assert got[1]["map"] == "spot"
    # What is served can be sent straight back.
    again = client.put("/api/schemas/sample/charts", json={"charts": got})
    assert again.status_code == 200, again.text
    assert again.json()["charts"] == got

    bad = client.put(
        "/api/schemas/sample/charts",
        json={"charts": [{"id": "x", "group_by": ["nowhere"]}]},
    )
    assert bad.status_code == 422
    assert (
        client.put("/api/schemas/nothing/charts", json={"charts": []}).status_code
        == 404
    )
    cleared = client.put("/api/schemas/sample/charts", json={"charts": []})
    assert cleared.json()["charts"] == []


def test_the_page_is_read_and_replaced_whole(client: TestClient):
    schema_id = _study(client)
    collection = client.post("/api/collections", json={"name": "survey"}).json()
    page = client.get("/api/dashboard").json()
    assert page["edited"] is False
    assert "storage" in page["widgets"]
    cards = [
        {"id": c["id"], "kind": c["kind"], "size": c["size"], "widget": c["widget"]}
        for c in page["cards"]
    ]
    cards.insert(
        0,
        {
            "id": "mine",
            "kind": "chart",
            "size": "wide",
            "title": "Deep ones per site",
            "chart": {"group_by": ["site"], "measures": ["count", "mean:depth"]},
            "records": {
                "schema": schema_id,
                "collection": collection["id"],
                "filter": {"field": "depth", "op": "gt", "value": 5},
            },
        },
    )
    saved = client.put("/api/dashboard", json={"cards": cards[:3]})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["edited"] is True
    assert [c["id"] for c in body["cards"]] == ["mine", cards[1]["id"], cards[2]["id"]]
    mine = body["cards"][0]
    assert mine["schema_name"] == "sample" and mine["collection_name"] == "survey"
    assert mine["chart"]["measures"] == ["count", "mean:depth"]
    assert mine["records"]["filter"]["field"] == "depth"
    # What is served can be saved again as it is.
    again = client.put(
        "/api/dashboard",
        json={
            "cards": [
                {
                    k: c[k]
                    for k in (
                        "id",
                        "kind",
                        "size",
                        "title",
                        "chart",
                        "records",
                        "widget",
                    )
                    if c.get(k) is not None
                }
                for c in body["cards"]
            ]
        },
    )
    assert again.status_code == 200, again.text

    for wrong in (
        {"id": "w", "kind": "widget", "widget": "weather"},
        {
            "id": "c",
            "kind": "chart",
            "chart": {"group_by": ["nowhere"]},
            "records": {"schema": schema_id},
        },
    ):
        assert client.put("/api/dashboard", json={"cards": [wrong]}).status_code == 422
    history = client.get("/api/audit/events", params={"limit": 10}).json()
    assert any(
        (e.get("entry") or {}).get("entity_type") == "dashboard"
        for e in history["items"]
    )
