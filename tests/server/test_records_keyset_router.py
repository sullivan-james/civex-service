"""Keyset (cursor) paging of record lists, sorted or not, and the `estimate`
flag on totals and the count endpoints (exact on SQLite)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _seed(client: TestClient, n: int = 23) -> None:
    client.post("/api/schemas", json={"name": "plot"})
    client.post("/api/schemas/plot/fields", json={"name": "size", "type": "integer"})
    client.post("/api/schemas/plot/fields", json={"name": "site", "type": "string"})
    client.post("/api/collections", json={"name": "survey"})
    for i in range(n):
        data: dict = {"site": f"s{i % 4}"}
        if i % 5:  # every fifth has no size: nulls sort last
            data["size"] = i % 7  # plenty of ties
        r = client.post(
            "/api/collections/survey/records",
            json={"schema_name": "plot", "data": data},
        )
        assert r.status_code == 201, r.text


def _walk(client: TestClient, path: str, params: dict, limit: int) -> list[dict]:
    items: list[dict] = []
    cursor = None
    for _ in range(100):
        q = {**params, "limit": limit, **({"cursor": cursor} if cursor else {})}
        r = client.get(path, params=q)
        assert r.status_code == 200, r.text
        body = r.json()
        items += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("never ended")


def _offset_walk(client: TestClient, path: str, params: dict) -> list[dict]:
    r = client.get(path, params={**params, "limit": 1000})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_every_sort_pages_to_the_same_list_as_one_big_page(client: TestClient):
    _seed(client)
    path = "/api/collections/survey/records"
    for sort in (
        [],
        ["size"],
        ["size:desc"],
        ["site:desc", "size"],
        ["@created_at:desc"],
        ["@kind", "size:desc"],
    ):
        params = {"schema": "plot", "sort": sort}
        # One page with offset 1 skips a row; compare against offset 0 via
        # the offset path (limit large enough for everything).
        whole = [r["id"] for r in _offset_walk(client, path, params)]
        assert len(whole) == 23
        for limit in (1, 4, 23, 50):
            paged = [r["id"] for r in _walk(client, path, params, limit)]
            assert paged == whole, (sort, limit)


def test_search_and_filter_pages(client: TestClient):
    _seed(client)
    path = "/api/collections/survey/records"
    params = {"schema": "plot", "search": "s1", "sort": ["size"]}
    whole = [r["id"] for r in _offset_walk(client, path, params)]
    assert whole
    assert [r["id"] for r in _walk(client, path, params, 2)] == whole


def test_stable_under_concurrent_inserts(client: TestClient):
    _seed(client, 10)
    path = "/api/collections/survey/records"
    first = client.get(path, params={"limit": 4}).json()
    seen = [r["id"] for r in first["items"]]
    client.post(
        "/api/collections/survey/records",
        json={"schema_name": "plot", "data": {"size": 1}},
    )
    cursor = first["next_cursor"]
    while cursor:
        page = client.get(path, params={"limit": 4, "cursor": cursor}).json()
        seen += [r["id"] for r in page["items"]]
        cursor = page["next_cursor"]
    assert len(seen) == len(set(seen))
    assert len(seen) >= 10  # none skipped; the new one comes last, unsorted


def test_cursor_rules(client: TestClient):
    _seed(client, 6)
    path = "/api/collections/survey/records"
    page = client.get(path, params={"limit": 2, "sort": "size", "schema": "plot"})
    cursor = page.json()["next_cursor"]
    assert cursor
    assert client.get(path, params={"cursor": "garbage"}).status_code == 422
    both = client.get(path, params={"cursor": cursor, "offset": 2})
    assert both.status_code == 422
    # A cursor made under one sort is refused under another.
    other = client.get(
        path, params={"cursor": cursor, "schema": "plot", "sort": "size:desc"}
    )
    assert other.status_code == 422
    # Offset still works, and has no cursor.
    off = client.get(path, params={"offset": 2, "limit": 2}).json()
    assert off["next_cursor"] is None and len(off["items"]) == 2


def test_estimate_is_exact_on_sqlite(client: TestClient):
    _seed(client, 7)
    listed = client.get(
        "/api/collections/survey/records", params={"estimate": "true"}
    ).json()
    assert listed["total"] == 7 and listed["total_estimated"] is False
    for path in ("/api/records/count", "/api/collections/survey/records/count"):
        r = client.get(path, params={"estimate": "true"})
        assert r.status_code == 200, r.text
        assert r.json() == {"count": 7, "estimated": False}
    assert client.get("/api/records/count").json()["count"] == 7
    assert client.get("/api/collections/nope/records/count").status_code == 404
