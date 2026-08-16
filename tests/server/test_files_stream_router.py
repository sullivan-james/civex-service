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
