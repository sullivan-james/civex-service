"""`/api/import`: look inside an uploaded spreadsheet, then bring it in a part
at a time, the way the import page does."""

from __future__ import annotations

from fastapi.testclient import TestClient

CSV = b"ID,Name,Age\n007,Ann,31\n012,Bob,x\n100,Cy,40\n"


def _upload(client: TestClient, raw: bytes = CSV, name: str = "people.csv") -> str:
    r = client.put(f"/api/files/stream?filename={name}", content=raw)
    assert r.status_code == 201
    return r.json()["sha256"]


def _body(sha: str, columns, **extra):
    return {
        "sha256": sha,
        "filename": "people.csv",
        "collection": "study",
        "kind": "person",
        "kind_label": "Person",
        "columns": columns,
        **extra,
    }


def test_a_spreadsheet_is_looked_into_and_brought_in(client: TestClient) -> None:
    assert client.post("/api/collections", json={"name": "study"}).status_code == 201
    sha = _upload(client)

    seen = client.post(
        "/api/import/inspect", json={"sha256": sha, "filename": "people.csv"}
    )
    assert seen.status_code == 200, seen.text
    sheet = seen.json()
    assert sheet["total"] == 3
    assert [c["key"] for c in sheet["columns"]] == ["id", "name", "age"]
    assert sheet["columns"][2]["dtype"] == "string"  # one cell is not a number

    columns = [
        {"heading": "ID", "field": "id", "create": True, "dtype": "string"},
        {"heading": "Name", "field": "name", "create": True, "dtype": "string"},
        {"heading": "Age", "field": "age", "create": True, "dtype": "integer"},
    ]
    check = client.post(
        "/api/import/run", json=_body(sha, columns, check=True, match_on=["id"])
    )
    assert check.status_code == 200, check.text
    assert check.json()["created"] == 2 and check.json()["skipped"] == 1
    assert "Row 3: age: 'x' is not a whole number" in check.json()["problems"]
    assert client.get("/api/schemas").json() == []  # a check keeps nothing

    batch = client.post("/api/audit/batches", json={"kind": "import"}).json()["id"]
    run = client.post(
        "/api/import/run",
        json=_body(sha, columns, match_on=["id"]),
        headers={"X-Civex-Batch": batch},
    )
    assert run.status_code == 200 and run.json()["done"] is True
    assert run.json() == {**check.json()}
    records = client.get("/api/records?schema=person")
    assert {r["data"]["id"] for r in records.json()} == {"007", "100"}
    event = client.get(f"/api/audit/batches/{batch}")
    assert event.status_code == 200  # one event of history for the import


def test_a_missing_file_or_collection_is_refused_plainly(client: TestClient) -> None:
    r = client.post(
        "/api/import/inspect", json={"sha256": "0" * 64, "filename": "a.csv"}
    )
    assert r.status_code == 404
    sha = _upload(client)
    r = client.post(
        "/api/import/run",
        json=_body(sha, [{"heading": "ID", "field": "id", "create": True}]),
    )
    assert r.status_code == 404  # no collection 'study'
