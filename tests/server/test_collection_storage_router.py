"""GET /api/store/collections/{id}: where a collection's files are."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from civex.config import load_config
from civex.context import build_local_context


def _file_record(ctx, collection: str, data: bytes, name: str, volume: str) -> None:
    ctx.store_svc.set_queue([volume])
    ref = ctx.file_svc._store.put(data, name)
    ctx.record_svc.add(collection, "doc", {"scan": ref.to_dict()})
    ctx.commit()


def _setup(tmp_path: Path):
    ctx = build_local_context(load_config())
    for name in ("a", "b"):
        path = tmp_path / name
        path.mkdir()
        ctx.store_svc.add_volume(name, str(path))
    return ctx


def _api_setup(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "doc", "description": None})
    client.post(
        "/api/schemas/doc/fields",
        json={"name": "scan", "dtype": "file", "required": False},
    )
    for c in ("one", "two"):
        client.post("/api/collections", json={"name": c, "description": None})
        client.post(f"/api/collections/{c}/schemas", json={"schemas": ["doc"]})


def test_a_collection_split_across_volumes_is_broken_down(
    client: TestClient, tmp_path: Path
) -> None:
    _api_setup(client)
    ctx = _setup(tmp_path)
    _file_record(ctx, "one", b"x" * 100, "p.bin", "a")
    _file_record(ctx, "one", b"y" * 300, "q.bin", "b")
    _file_record(ctx, "one", b"z" * 500, "r.bin", "b")
    _file_record(ctx, "two", b"y" * 300, "q.bin", "b")  # shares one file with "one"
    cid = str(ctx.dataset_svc.get("one").id)
    ctx.close()

    body = client.get(f"/api/store/collections/{cid}").json()

    assert body["files"] == 3 and body["unlocated_files"] == 0
    by = {v["volume"]: v for v in body["volumes"]}
    assert (by["a"]["files"], by["a"]["bytes"], by["a"]["shared_files"]) == (1, 100, 0)
    assert (by["b"]["files"], by["b"]["bytes"], by["b"]["shared_files"]) == (2, 800, 1)
    assert [v["volume"] for v in body["volumes"]] == ["b", "a"]  # largest first
    assert by["b"]["available"] is True and by["b"]["state"] == "online"


def test_an_empty_collection_has_no_volumes(client: TestClient) -> None:
    _api_setup(client)
    ctx = build_local_context(load_config())
    cid = str(ctx.dataset_svc.get("one").id)
    ctx.close()
    body = client.get(f"/api/store/collections/{cid}").json()
    assert body["files"] == 0 and body["volumes"] == []


def test_an_unplugged_volume_is_still_listed_with_its_state(
    client: TestClient, tmp_path: Path
) -> None:
    _api_setup(client)
    ctx = _setup(tmp_path)
    _file_record(ctx, "one", b"x" * 100, "p.bin", "a")
    cid = str(ctx.dataset_svc.get("one").id)
    ctx.close()
    (tmp_path / "a").rename(tmp_path / "a-unplugged")

    (vol,) = client.get(f"/api/store/collections/{cid}").json()["volumes"]

    assert vol["volume"] == "a" and vol["available"] is False
    assert vol["state"] == "offline" and vol["files"] == 1


def test_an_unknown_collection_is_404(client: TestClient) -> None:
    assert client.get(f"/api/store/collections/{uuid.uuid4()}").status_code == 404


def test_every_collection_is_answered_in_one_call_and_matches_the_single_view(
    client: TestClient, tmp_path: Path
) -> None:
    _api_setup(client)
    ctx = _setup(tmp_path)
    _file_record(ctx, "one", b"x" * 100, "p.bin", "a")
    _file_record(ctx, "one", b"y" * 300, "q.bin", "b")
    _file_record(ctx, "two", b"y" * 300, "q.bin", "b")  # shared with "one"
    ids = {c: str(ctx.dataset_svc.get(c).id) for c in ("one", "two")}
    ctx.close()

    everything = {
        r["collection_id"]: r for r in client.get("/api/store/collections").json()
    }

    assert set(everything) == set(ids.values())
    for cid in ids.values():  # one rule: the bulk view is the single view, repeated
        assert everything[cid] == client.get(f"/api/store/collections/{cid}").json()
    two = everything[ids["two"]]
    assert two["files"] == 1 and two["volumes"][0]["shared_files"] == 1


def test_collections_without_files_are_left_out_of_the_list(client: TestClient) -> None:
    _api_setup(client)
    assert client.get("/api/store/collections").json() == []


def test_volumes_report_files_no_collection_uses(
    client: TestClient, tmp_path: Path
) -> None:
    """The per-volume usage splits out what is used by nothing (reclaimable) and
    what workflow run history alone keeps, so "Civex uses 442 MB" can be explained."""
    from civex.db.models import FileReference

    _api_setup(client)
    ctx = _setup(tmp_path)
    _file_record(ctx, "one", b"x" * 100, "used.bin", "a")
    ctx.store_svc.set_queue(["a"])
    ctx.file_svc._store.put(b"o" * 700, "orphan.bin")  # nothing refers to it
    history = ctx.file_svc._store.put(b"h" * 50, "input.bin")
    ctx._session.add(
        FileReference(sha256=history.sha256, record_id=None, job_id=_job_id(ctx))
    )
    ctx.commit()
    ctx.close()

    by = {v["name"]: v for v in client.get("/api/store/volumes").json()}

    assert (by["a"]["unused_files"], by["a"]["unused_bytes"]) == (1, 700)
    assert (by["a"]["history_files"], by["a"]["history_bytes"]) == (1, 50)
    assert by["b"]["unused_files"] == 0 and by["b"]["history_files"] == 0


def _job_id(ctx):
    from civex.db.models import Record, WorkflowJob

    job = WorkflowJob(
        workflow_name="w",
        record_id=ctx._session.query(Record).first().id,
        trigger="manual",
        status="completed",
    )
    ctx._session.add(job)
    ctx._session.flush()
    return job.id
