"""HTTP-level tests for PUT /api/files/stream and /api/files/batch."""

from __future__ import annotations

import hashlib
import json

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
    monkeypatch.setattr(
        SyncService,
        "not_here_reasons",
        lambda self, shas: {
            s: ("It is still only on 'backup'.", "It arrives.") for s in shas
        },
    )
    resp = client.get(f"/api/files/{sha}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "It is still only on 'backup'. It arrives."

    def fetched(self, sha256):
        self._files.put(payload, "x.bin", None)
        return True

    monkeypatch.setattr(SyncService, "fetch_file", fetched)
    resp = client.get(f"/api/files/{sha}?filename=scan.bin")
    assert resp.status_code == 200 and resp.content == payload


def _batch(*files: tuple[str, bytes]) -> bytes:
    manifest = json.dumps([{"name": n, "size": len(b)} for n, b in files])
    return manifest.encode() + b"\n" + b"".join(b for _, b in files)


def test_a_batch_stores_every_file_in_one_request(client: TestClient) -> None:
    files = [
        ("a.wav", b"a" * 10),
        ("empty.txt", b""),
        ("big.bin", b"z" * (3 * 1024 * 1024 + 7)),  # spans many stream chunks
        ("again.wav", b"a" * 10),  # the same content as a.wav: stored once
    ]
    resp = client.put("/api/files/batch", content=_batch(*files))
    assert resp.status_code == 200
    body = resp.json()
    assert body["stopped"] is None
    assert [f["filename"] for f in body["files"]] == [n for n, _ in files]
    for got, (_, data) in zip(body["files"], files):
        assert got["sha256"] == hashlib.sha256(data).hexdigest()
        assert got["size"] == len(data)
        assert client.get(f"/api/files/{got['sha256']}").content == data


def test_a_batch_that_runs_out_of_room_says_which_file_and_why(
    client: TestClient,
) -> None:
    client.patch("/api/store/volumes/default", json={"allocated_gb": 0.0000001})

    resp = client.put(
        "/api/files/batch",
        content=_batch(("big.bin", b"y" * (1024 * 1024)), ("next.bin", b"n" * 10)),
    )
    # A whole answer, not a dropped connection: the rest of the body was read.
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"] == []
    assert body["stopped"]["index"] == 0 and body["stopped"]["message"]


def test_a_batch_shorter_than_its_list_is_refused(client: TestClient) -> None:
    body = json.dumps([{"name": "a", "size": 100}]).encode() + b"\n" + b"only this"
    assert client.put("/api/files/batch", content=body).status_code == 422
    assert client.put("/api/files/batch", content=b"not a list").status_code == 422
