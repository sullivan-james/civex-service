"""HTTP contract of the authority's peer API (/api/sync/v1/*): it is invisible
unless the instance serves, lets in only a device that joined with an invite and
signed in with its key, and reaches a remote host even though the rest of the
API does not."""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from civex import keys
from civex.config import load_config, save_config
from civex.context import build_local_context
from civex.domain.sync import (
    PROTOCOL_MAX,
    PROTOCOL_MIN,
    protocol_header,
    session_request,
)


def _invite(on: bool = True, name: str = "laptop") -> str:
    config = load_config()
    config.sync.serve = on
    save_config(config)
    ctx = build_local_context(config)
    try:
        _, invite = ctx.device_keys.invite(name)
        ctx.commit()
    finally:
        ctx.close()
    return invite


@pytest.fixture()
def serve(sign_in_over_http):
    """serve(client) -> serve, and a signed-in device's session token."""
    return lambda client: sign_in_over_http(client, _invite())


def _headers(token: str, protocol: str | None = None):
    return {
        "Authorization": f"Bearer {token}",
        "X-Civex-Protocol": protocol or protocol_header(),
    }


def test_the_peer_api_is_not_there_unless_the_instance_serves(client: TestClient):
    invite = _invite(on=False)
    plain = {"X-Civex-Protocol": protocol_header()}
    assert client.get("/api/sync/v1/hello", headers=_headers("x")).status_code == 404
    joining = client.post("/api/sync/v1/join", headers=plain, json={"invite": invite})
    assert joining.status_code == 404


def test_hello_names_the_project(serve, client: TestClient):
    token = serve(client)
    resp = client.get("/api/sync/v1/hello", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["protocol_version"] == PROTOCOL_MAX
    assert (body["protocol_min"], body["protocol_max"]) == (PROTOCOL_MIN, PROTOCOL_MAX)
    assert body["server_version"]
    assert body["empty"] is True
    assert body["device_name"] == "laptop"


def test_a_call_without_a_valid_session_is_refused(serve, client: TestClient):
    serve(client)
    plain = {"X-Civex-Protocol": protocol_header()}
    assert client.get("/api/sync/v1/hello", headers=plain).status_code == 401
    assert client.get("/api/sync/v1/hello", headers=_headers("nope")).status_code == 401


def test_an_invite_joins_one_device_once(sign_in_over_http, client: TestClient):
    invite = _invite()
    sign_in_over_http(client, invite)
    again = client.post(
        "/api/sync/v1/join",
        headers={"X-Civex-Protocol": protocol_header()},
        json={
            "invite": invite,
            "device_id": str(uuid.uuid4()),
            "public_key": keys.public_of(keys.new_private_key()),
        },
    )
    assert again.status_code == 401


def test_signing_in_needs_the_key_the_device_joined_with(serve, client: TestClient):
    serve(client)
    device_id = str(uuid.uuid4())
    at = int(time.time())
    forged = keys.sign(keys.new_private_key(), session_request("x", device_id, at))
    resp = client.post(
        "/api/sync/v1/session",
        headers={"X-Civex-Protocol": protocol_header()},
        json={"device_id": device_id, "at": at, "signature": forged},
    )
    assert resp.status_code == 401


def test_failed_joins_are_slowed_down(client: TestClient):
    _invite()
    plain = {"X-Civex-Protocol": protocol_header()}
    guess = {
        "invite": "civex_inv_guess",
        "device_id": str(uuid.uuid4()),
        "public_key": keys.public_of(keys.new_private_key()),
    }
    codes = [
        client.post("/api/sync/v1/join", headers=plain, json=guess).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10 and codes[-1] == 429


@pytest.mark.parametrize(
    "sent, agreed",
    [
        (protocol_header(), PROTOCOL_MAX),
        # A newer device that still speaks this server's version.
        (f"{PROTOCOL_MIN}-{PROTOCOL_MAX + 3}", PROTOCOL_MAX),
    ],
)
def test_a_device_and_the_server_agree_on_the_newest_version_both_speak(
    serve, client: TestClient, sent: str, agreed: int
):
    token = serve(client)
    resp = client.get("/api/sync/v1/hello", headers=_headers(token, protocol=sent))
    assert resp.status_code == 200, resp.text
    assert resp.json()["protocol_version"] == agreed


@pytest.mark.parametrize(
    "sent, update",
    [
        (str(PROTOCOL_MIN - 1), "on the device"),
        (f"{PROTOCOL_MAX + 1}-{PROTOCOL_MAX + 2}", "on this server"),
        ("nonsense", "on the device"),
    ],
)
def test_a_version_neither_speaks_is_refused_saying_which_side_to_update(
    serve, client: TestClient, sent: str, update: str
):
    token = serve(client)
    resp = client.get("/api/sync/v1/hello", headers=_headers(token, protocol=sent))
    assert resp.status_code == 426
    detail = resp.json()["detail"]
    assert update in detail["message"]
    assert (detail["protocol_min"], detail["protocol_max"]) == (
        PROTOCOL_MIN,
        PROTOCOL_MAX,
    )


def test_a_malformed_push_is_refused(serve, client: TestClient):
    token = serve(client)
    resp = client.post(
        "/api/sync/v1/push", headers=_headers(token), json={"entries": [{"x": 1}]}
    )
    assert resp.status_code == 422


def test_an_unknown_snapshot_kind_is_refused(serve, client: TestClient):
    token = serve(client)
    resp = client.get("/api/sync/v1/snapshot/bogus", headers=_headers(token))
    assert resp.status_code == 422


def test_files_are_stored_by_hash_and_can_be_fetched(serve, client: TestClient):
    import hashlib

    token = serve(client)
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


def test_a_file_whose_bytes_do_not_match_its_hash_is_refused(serve, client: TestClient):
    token = serve(client)
    wrong = "0" * 64
    resp = client.put(
        f"/api/sync/v1/files/{wrong}", headers=_headers(token), content=b"x"
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("path", ["/api/schemas", "/api/collections"])
def test_a_remote_host_reaches_only_the_peer_api_on_a_serving_instance(
    serve, client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
):
    token = serve(client)
    monkeypatch.setenv("CIVEX_ALLOW_REMOTE", "1")
    remote = {"Host": "authority.example.com"}
    assert client.get(path, headers=remote).status_code == 403
    peer = client.get("/api/sync/v1/hello", headers={**_headers(token), **remote})
    assert peer.status_code == 200


def test_the_sync_only_server_has_nothing_but_the_peer_api(serve, project_dir):
    """What a proxy in front of an authority is pointed at. A proxy that sends
    `Host: localhost` must not reach the app, whose API has no authentication."""
    from civex.server.app import create_sync_app

    server = TestClient(create_sync_app(), raise_server_exceptions=False)
    token = serve(server)
    local = {"Host": "localhost"}
    assert server.get("/api/sync/v1/hello", headers=_headers(token)).status_code == 200
    assert server.get("/api/schemas", headers=local).status_code == 404
    assert server.get("/api/remote", headers=local).status_code == 404
    assert server.get("/openapi.json", headers=local).status_code == 404


def test_serve_sync_only_refuses_a_project_that_is_not_an_authority(project_dir):
    from typer.testing import CliRunner

    from civex.main import app

    _invite(on=False)
    result = CliRunner().invoke(app, ["serve", "--sync-only"])
    assert result.exit_code == 1
    assert "civex sync authority enable" in result.output


def _asking(db_url: str, host: str = "10.0.0.1"):
    """A request for a project on `db_url`, from `host`."""
    from types import SimpleNamespace

    project = SimpleNamespace(config=SimpleNamespace(db=SimpleNamespace(url=db_url)))
    return SimpleNamespace(
        client=SimpleNamespace(host=host), state=SimpleNamespace(project=project)
    )


def test_two_projects_do_not_share_a_lockout():
    from fastapi import HTTPException

    from civex.server.routers.sync_peer import _Attempts

    attempts = _Attempts()
    a, b = (
        _asking("postgresql://h/db?search_path=repo_a"),
        _asking("postgresql://h/db?search_path=repo_b"),
    )
    for _ in range(_Attempts.LIMIT):
        attempts.failed(a)
    with pytest.raises(HTTPException) as locked:
        attempts.check(a)
    assert locked.value.status_code == 429
    attempts.check(b)  # same caller address, another project: not slowed
    attempts.failed(b)
    attempts.check(b)


def test_one_project_still_locks_a_caller_out_and_others_callers_are_free():
    from fastapi import HTTPException

    from civex.server.routers.sync_peer import _Attempts

    attempts = _Attempts()
    url = "postgresql://h/db?search_path=repo_a"
    for _ in range(_Attempts.LIMIT):
        attempts.failed(_asking(url))
    with pytest.raises(HTTPException):
        attempts.check(_asking(url))
    attempts.check(_asking(url, host="10.0.0.2"))


def test_projects_sharing_one_engine_are_still_counted_apart(tmp_path):
    """A host hands every project one engine: only the settings' URL (with the
    project's schema) tells them apart."""
    from types import SimpleNamespace

    from fastapi import HTTPException
    from sqlalchemy import create_engine

    from civex.config import Config, DBConfig
    from civex.project import Project
    from civex.server.routers.sync_peer import _Attempts

    shared = create_engine("sqlite://")

    def project(schema: str) -> Project:
        url = f"postgresql://u:s3cret@h/db?options=-csearch_path%3D{schema}"
        cfg = Config(project_root=tmp_path, db=DBConfig(url=url))
        return Project(config=cfg, config_store=SimpleNamespace(), engine=shared)

    def asking(schema: str):
        return SimpleNamespace(
            client=SimpleNamespace(host="10.0.0.1"),
            state=SimpleNamespace(project=project(schema)),
        )

    attempts = _Attempts()
    for _ in range(_Attempts.LIMIT):
        attempts.failed(asking("repo_a"))
    with pytest.raises(HTTPException):
        attempts.check(asking("repo_a"))
    attempts.check(asking("repo_b"))
    attempts.failed(asking("repo_b"))
    assert not any("s3cret" in str(k) for k in attempts._failed)


def test_the_failed_attempts_stay_bounded_and_expire(monkeypatch):
    from civex.server.routers import sync_peer
    from civex.server.routers.sync_peer import _Attempts

    attempts = _Attempts()
    monkeypatch.setattr(_Attempts, "MAX_KEYS", 100)
    for n in range(1000):
        attempts.failed(_asking(f"postgresql://h/db?schema=repo_{n}"))
        assert len(attempts._failed) <= 100
    # what expired goes, even when nobody asks about it again
    now = sync_peer.time.monotonic()
    monkeypatch.setattr(sync_peer.time, "monotonic", lambda: now + 3600)
    for n in range(1000, 1012):
        attempts.failed(_asking(f"postgresql://h/db?schema=repo_{n}"))
    assert len(attempts._failed) == 12  # (only the new ones are left)
