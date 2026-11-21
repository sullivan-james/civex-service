"""HTTP contract for releases."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _study(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "sample"})
    client.post("/api/schemas/sample/fields", json={"name": "site", "type": "string"})
    for name in ("north", "south"):
        client.post("/api/collections", json={"name": name})
        made = client.post(
            f"/api/collections/{name}/records",
            json={"schema_name": "sample", "data": {"site": name}},
        )
        assert made.status_code == 201, made.text


def test_plan_make_read_cite_verify_and_download(client: TestClient):
    _study(client)
    plan = client.post("/api/releases/plan", json={"collections": ["north"]})
    assert plan.status_code == 200, plan.text
    assert plan.json()["records"] == 1

    made = client.post(
        "/api/releases",
        json={
            "name": "v1",
            "title": "Survey",
            "authors": ["Ada Lovelace"],
            "doi": "10.1234/abc",
            "collections": ["north"],
        },
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["content_hash"].startswith("sha256:")
    assert body["scope"] == {"collections": ["north"]}
    assert body["file_name"] == "release-v1.civex.zip"

    assert [r["name"] for r in client.get("/api/releases").json()] == ["v1"]
    assert client.get("/api/releases/v1").json()["id"] == body["id"]
    assert (
        client.post("/api/releases", json={"name": "v1", "title": "x"}).status_code
        == 409
    )

    cite = client.get("/api/releases/v1/citation").json()
    assert "(Version v1)" in cite["text"] and cite["bibtex"].startswith("@misc{")
    assert "cff-version: 1.2.0" in cite["cff"]

    verified = client.post("/api/releases/v1/verify").json()
    assert verified["matches"] is True and verified["problems"] == []

    bundle = client.get("/api/releases/v1/bundle", follow_redirects=False)
    assert bundle.status_code == 307
    assert bundle.headers["location"].startswith(f"../../files/{body['bundle_sha256']}")
    download = client.get("/api/releases/v1/bundle")
    assert download.status_code == 200
    assert download.content[:2] == b"PK"


def test_correct_withdraw_and_changes_since(client: TestClient):
    _study(client)
    client.post("/api/releases", json={"name": "v1", "title": "Survey"})
    fixed = client.patch("/api/releases/v1", json={"title": "The survey"})
    assert fixed.status_code == 200 and fixed.json()["title"] == "The survey"
    bad = client.patch("/api/releases/v1", json={"doi": "nope"})
    assert bad.status_code == 422

    client.post(
        "/api/collections/south/records",
        json={"schema_name": "sample", "data": {"site": "more"}},
    )
    since = client.get("/api/releases/v1/changes").json()
    assert since["comparable"] and since["added"] == 1
    assert since["collections"][0]["collection"] == "south"

    gone = client.post("/api/releases/v1/withdraw", json={"reason": "wrong units"})
    assert gone.status_code == 200 and gone.json()["withdrawn_reason"] == "wrong units"
    assert client.get("/api/releases/nope").status_code == 404
