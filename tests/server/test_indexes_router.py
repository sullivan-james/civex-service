"""`/db/indexes` and `/schemas/{s}/fields/{f}/index`: the HTTP side of
`IndexService`. Building happens on `index_jobs`' thread; these tests run it
by hand to stay deterministic."""

from __future__ import annotations

from civex.domain.field_index import IndexProgress
from civex.services.index_jobs import index_jobs


def _schema(client) -> None:
    assert client.post("/api/schemas", json={"name": "sample"}).status_code == 201
    r = client.post(
        "/api/schemas/sample/fields", json={"name": "depth", "type": "float"}
    )
    assert r.status_code == 201, r.text


def test_ask_for_an_index_and_see_it_built(client, monkeypatch) -> None:
    # The app started the real thread; it would race this test's own tick for
    # the project's upkeep lock (whoever loses leaves it to the other).
    index_jobs.shutdown()
    index_jobs._stop.clear()  # so the tick below isn't told to stop
    requested = []
    monkeypatch.setattr(index_jobs, "request", lambda: requested.append(True))
    _schema(client)

    r = client.get("/api/schemas/sample/fields/depth/index")
    assert r.status_code == 200
    assert r.json()["indexed"] is False

    r = client.put("/api/schemas/sample/fields/depth/index", json={"indexed": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["indexed"] is True and body["reasons"] == ["chosen"]
    assert body["built"] is False
    assert requested  # the background thread was asked

    report = client.get("/api/db/indexes").json()
    assert report["in_step"] is False
    assert [f["field"] for f in report["fields"]] == ["depth"]

    index_jobs._tick(force=True, since_statistics=0)  # what the thread does
    assert client.get("/api/schemas/sample/fields/depth/index").json()["built"] is True
    assert client.get("/api/db/indexes").json()["in_step"] is True

    assert client.post("/api/db/indexes/reconcile").status_code == 202


def test_a_field_that_cant_be_indexed_is_refused(client) -> None:
    _schema(client)
    client.post("/api/schemas/sample/fields", json={"name": "doc", "type": "file"})
    r = client.put("/api/schemas/sample/fields/doc/index", json={"indexed": True})
    assert r.status_code == 422
    assert client.get("/api/schemas/sample/fields/nope/index").status_code == 404


def test_a_build_in_progress_is_reported_for_the_status_bar(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        index_jobs,
        "progress",
        IndexProgress(done=1, total=4, schema_label="Sample", field_label="Depth"),
    )
    report = client.get("/api/db/indexes").json()
    assert report["building"] is True
    assert report["progress"] == {
        "done": 1,
        "total": 4,
        "schema_label": "Sample",
        "field_label": "Depth",
        "waiting": False,
        "yielded": 0,
    }


def test_changing_a_uniqueness_key_asks_for_the_indexes(client, monkeypatch) -> None:
    requested = []
    monkeypatch.setattr(index_jobs, "request", lambda: requested.append(True))
    _schema(client)
    r = client.put("/api/schemas/sample/unique-keys", json={"keys": [["depth"]]})
    assert r.status_code == 200, r.text
    assert requested
