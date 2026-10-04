"""HTTP-level tests for /api/store/transfers."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from civex.config import load_config
from civex.context import build_local_context


def _setup(client: TestClient, tmp_path: Path, files: int = 5) -> None:
    ctx = build_local_context(load_config())
    for name in ("a", "b"):
        path = tmp_path / "mnt" / name
        path.mkdir(parents=True)
        ctx.store_svc.add_volume(name, str(path))
    ctx.store_svc.set_queue(["a"])
    for i in range(files):
        ctx.file_svc._store.put(f"file {i} ".encode() * 50, f"f{i}.txt")
    ctx.commit()
    ctx.close()


def _body(**kw):
    return {"kind": "drain", "sources": ["a"], "targets": ["b"], **kw}


def _wait(client: TestClient, tid: str, status: str) -> dict:
    for _ in range(100):
        got = client.get(f"/api/store/transfers/{tid}").json()
        if got["status"] == status:
            return got
        time.sleep(0.1)
    raise AssertionError(f"never became {status}: {got['status']}")


def test_preview_changes_nothing(client: TestClient, tmp_path: Path) -> None:
    _setup(client, tmp_path)
    resp = client.post("/api/store/transfers/preview", json=_body())
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["files"] == 5 and plan["can_proceed"] is True
    assert client.get("/api/store/transfers").json() == []


def test_a_transfer_runs_to_completion(client: TestClient, tmp_path: Path) -> None:
    _setup(client, tmp_path)
    resp = client.post("/api/store/transfers", json=_body())
    assert resp.status_code == 202
    done = _wait(client, resp.json()["id"], "completed")
    assert done["progress"]["files_done"] == 5
    assert len(client.get("/api/store/transfers").json()) == 1


def test_an_impossible_transfer_is_refused_with_reasons(
    client: TestClient, tmp_path: Path
) -> None:
    _setup(client, tmp_path)
    resp = client.post(
        "/api/store/transfers",
        json={"kind": "drain", "sources": ["a"], "targets": ["a"]},
    )
    assert resp.status_code == 422


def test_pausing_a_finished_transfer_is_a_conflict(
    client: TestClient, tmp_path: Path
) -> None:
    _setup(client, tmp_path, files=1)
    tid = client.post("/api/store/transfers", json=_body()).json()["id"]
    _wait(client, tid, "completed")
    assert client.post(f"/api/store/transfers/{tid}/pause").status_code == 409


def test_an_unknown_transfer_is_404(client: TestClient) -> None:
    resp = client.get("/api/store/transfers/00000000-0000-4000-8000-000000000000")
    assert resp.status_code == 404
