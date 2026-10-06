"""HTTP contract of the authority's peer API (/api/sync/v1/*): it is invisible
unless the instance serves, needs a device token, and reaches a remote host
even though the rest of the API does not."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from civex.config import load_config, save_config
from civex.context import build_local_context
from civex.domain.sync import PROTOCOL_VERSION

DEVICE = str(uuid.uuid4())


def _serve(on: bool = True) -> str:
    config = load_config()
    config.sync.serve = on
    save_config(config)
    ctx = build_local_context(config)
    try:
        _, token = ctx.authority_svc.add_device("laptop")
        ctx.commit()
    finally:
        ctx.close()
    return token


def _headers(token: str, device: str = DEVICE, protocol: int = PROTOCOL_VERSION):
    return {
        "Authorization": f"Bearer {token}",
        "X-Civex-Device": device,
        "X-Civex-Protocol": str(protocol),
    }


def test_the_peer_api_is_not_there_unless_the_instance_serves(client: TestClient):
    token = _serve(on=False)
    assert client.get("/api/sync/v1/hello", headers=_headers(token)).status_code == 404


def test_hello_names_the_project(client: TestClient):
    token = _serve()
    resp = client.get("/api/sync/v1/hello", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["protocol_version"] == PROTOCOL_VERSION
    assert body["empty"] is True
    assert body["device_name"] == "laptop"


def test_a_call_without_a_valid_token_is_refused(client: TestClient):
    _serve()
    assert client.get("/api/sync/v1/hello").status_code == 401
    assert client.get("/api/sync/v1/hello", headers=_headers("nope")).status_code == 401


def test_a_token_is_tied_to_the_first_device_that_uses_it(client: TestClient):
    token = _serve()
    assert client.get("/api/sync/v1/hello", headers=_headers(token)).status_code == 200
    other = client.get(
        "/api/sync/v1/hello", headers=_headers(token, device=str(uuid.uuid4()))
    )
    assert other.status_code == 403


def test_a_different_protocol_is_refused_with_426(client: TestClient):
    token = _serve()
    resp = client.get("/api/sync/v1/hello", headers=_headers(token, protocol=99))
    assert resp.status_code == 426


def test_a_malformed_push_is_refused(client: TestClient):
    token = _serve()
    resp = client.post(
        "/api/sync/v1/push", headers=_headers(token), json={"entries": [{"x": 1}]}
    )
    assert resp.status_code == 422


def test_an_unknown_snapshot_kind_is_refused(client: TestClient):
    token = _serve()
    resp = client.get("/api/sync/v1/snapshot/bogus", headers=_headers(token))
    assert resp.status_code == 422


def test_files_are_stored_by_hash_and_can_be_fetched(client: TestClient):
    import hashlib

    token = _serve()
    data = b"some bytes"
    sha = hashlib.sha256(data).hexdigest()
    miss = client.post(
        "/api/sync/v1/files/missing", headers=_headers(token), json={"sha256": [sha]}
    )
    assert miss.json()["missing"] == [sha]
    put = client.put(f"/api/sync/v1/files/{sha}", headers=_headers(token), content=data)
    assert put.status_code == 204, put.text
    got = client.get(f"/api/sync/v1/files/{sha}", headers=_headers(token))
    assert got.content == data
    miss = client.post(
        "/api/sync/v1/files/missing", headers=_headers(token), json={"sha256": [sha]}
    )
    assert miss.json()["missing"] == []


def test_a_file_whose_bytes_do_not_match_its_hash_is_refused(client: TestClient):
    token = _serve()
    wrong = "0" * 64
    resp = client.put(
        f"/api/sync/v1/files/{wrong}", headers=_headers(token), content=b"x"
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("path", ["/api/schemas", "/api/collections"])
def test_a_remote_host_reaches_only_the_peer_api_on_a_serving_instance(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
):
    token = _serve()
    monkeypatch.setenv("CIVEX_ALLOW_REMOTE", "1")
    remote = {"Host": "authority.example.com"}
    assert client.get(path, headers=remote).status_code == 403
    peer = client.get("/api/sync/v1/hello", headers={**_headers(token), **remote})
    assert peer.status_code == 200
