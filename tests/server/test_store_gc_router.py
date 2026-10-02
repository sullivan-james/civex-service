"""HTTP-level tests for POST /api/store/gc."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_gc_dry_run_does_not_delete(client: TestClient) -> None:
    from civex.config import load_config
    from civex.context import build_local_context

    client.post("/api/schemas", json={"name": "doc", "description": None})
    client.post("/api/collections", json={"name": "study", "description": None})

    ctx = build_local_context(load_config())
    ref = ctx.file_svc._store.put(b"orphan", "orphan.txt")
    ctx.commit()
    ctx.close()

    resp = client.post("/api/store/gc", json={"grace_days": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["deleted_count"] == 1
    assert body["deleted"][0]["sha256"] == ref.sha256

    ctx2 = build_local_context(load_config())
    assert ctx2.file_svc._store.exists(ref.sha256)
    ctx2.close()


def test_gc_apply_deletes_unreferenced_objects(client: TestClient) -> None:
    from civex.config import load_config
    from civex.context import build_local_context

    client.post("/api/schemas", json={"name": "doc", "description": None})
    client.post("/api/collections", json={"name": "study", "description": None})

    ctx = build_local_context(load_config())
    ref = ctx.file_svc._store.put(b"orphan", "orphan.txt")
    ctx.commit()
    ctx.close()

    resp = client.post("/api/store/gc", json={"apply": True, "grace_days": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is False
    assert body["deleted_count"] == 1

    ctx2 = build_local_context(load_config())
    assert not ctx2.file_svc._store.exists(ref.sha256)
    ctx2.close()


def test_gc_defaults_to_dry_run_with_no_body(client: TestClient) -> None:
    resp = client.post("/api/store/gc", json={})
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True
    assert resp.json()["grace_days"] == 14


def test_volumes_report_state_and_adopt_restores_a_marker(
    client: TestClient, tmp_path
) -> None:
    drive = tmp_path / "usb"
    drive.mkdir()
    added = client.post("/api/store/volumes", json={"name": "usb", "path": str(drive)})
    assert added.status_code == 201
    assert added.json()["state"] == "online"

    (drive / ".civex-volume").unlink()
    listed = {v["name"]: v for v in client.get("/api/store/volumes").json()}
    assert listed["usb"]["state"] == "wrong_drive"
    assert listed["usb"]["available"] is False
    assert "adopt it" in listed["usb"]["fix"]

    adopted = client.post("/api/store/volumes/usb/adopt")
    assert adopted.status_code == 200
    assert adopted.json()["state"] == "online"

    assert client.post("/api/store/volumes/nope/adopt").status_code == 404
