"""HTTP-level tests for PUT /api/files/stream."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient


def test_stream_upload_roundtrips_and_dedupes(client: TestClient) -> None:
    payload = b"z" * (2 * 1024 * 1024)
    expected_sha = hashlib.sha256(payload).hexdigest()

    resp = client.put(
        "/api/files/stream?filename=big.bin",
        content=payload,
        headers={"content-length": str(len(payload))},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["sha256"] == expected_sha
    assert body["size"] == len(payload)

    resp2 = client.put("/api/files/stream?filename=big.bin", content=payload)
    assert resp2.status_code == 201
    assert resp2.json()["sha256"] == expected_sha

    dl = client.get(f"/api/files/{expected_sha}")
    assert dl.status_code == 200
    assert hashlib.sha256(dl.content).hexdigest() == expected_sha


def test_stream_upload_rejects_when_allocation_too_small(client: TestClient) -> None:
    client.patch("/api/store/volumes/default", json={"allocated_gb": 0.0000001})

    payload = b"y" * (1024 * 1024)
    resp = client.put(
        "/api/files/stream?filename=big.bin",
        content=payload,
        headers={"content-length": str(len(payload))},
    )
    assert resp.status_code == 507


def test_a_file_not_here_is_fetched_from_the_server_when_opened(
    client: TestClient, monkeypatch
) -> None:
    from civex.domain.sync import SyncError
    from civex.services.sync_service import SyncService

    payload = b"added on another device"
    sha = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(SyncService, "fetches_files", property(lambda self: True))

    def unreachable(self, sha256):
        raise SyncError("Could not reach the server")

    monkeypatch.setattr(SyncService, "fetch_file", unreachable)
    resp = client.get(f"/api/files/{sha}")
    assert resp.status_code == 503 and "can't be reached" in resp.json()["detail"]

    monkeypatch.setattr(SyncService, "fetch_file", lambda self, sha256: False)
    resp = client.get(f"/api/files/{sha}")
    assert resp.status_code == 404
    assert "hasn't reached the server" in resp.json()["detail"]

    def fetched(self, sha256):
        self._files.put(payload, "x.bin", None)
        return True

    monkeypatch.setattr(SyncService, "fetch_file", fetched)
    resp = client.get(f"/api/files/{sha}?filename=scan.bin")
    assert resp.status_code == 200 and resp.content == payload
