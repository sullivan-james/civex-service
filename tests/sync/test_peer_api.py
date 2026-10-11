"""The authority's HTTP side: what a device is told must already be saved, and a
joining device reads pages that follow on from a thing, not from a count."""

from __future__ import annotations


import pytest

from civex.config import load_config, save_config
from civex.context import AppContext
from civex.domain.sync import protocol_header


@pytest.fixture()
def serving(ctx, client, sign_in_over_http):
    config = load_config()
    config.sync.serve = True
    save_config(config)
    _, invite = ctx.device_keys.invite("laptop")
    ctx.commit()
    headers = {
        "Authorization": f"Bearer {sign_in_over_http(client, invite)}",
        "X-Civex-Protocol": protocol_header(),
    }
    return client, headers


def test_a_device_is_not_told_done_when_saving_failed(serving, monkeypatch):
    """The answer to a push says what was taken; the device then never sends it
    again. If saving fails after the answer has gone, the change is lost. So
    the work is saved first, and a failure to save is the answer."""
    client, headers = serving

    def fail(self):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(AppContext, "commit", fail)
    reply = client.post("/api/sync/v1/push", json={"entries": []}, headers=headers)
    assert reply.status_code == 500

    reply = client.get("/api/sync/v1/feed?after=0", headers=headers)
    assert reply.status_code == 500


def test_snapshot_pages_follow_on_with_a_cursor(serving, ctx):
    client, headers = serving
    for name in ("one", "two", "three"):
        ctx.schema_svc.create(name)
    ctx.commit()

    seen: list[str] = []
    after = None
    while True:
        params = {"limit": 2} | ({"after": after} if after else {})
        page = client.get(
            "/api/sync/v1/snapshot/schema", params=params, headers=headers
        ).json()
        seen += [item["name"] for item in page["items"]]
        if not page["more"]:
            assert page["next"] is None
            break
        after = page["next"]
    assert sorted(seen) == ["one", "three", "two"]


def test_a_cursor_that_is_not_one_is_refused(serving):
    client, headers = serving
    reply = client.get(
        "/api/sync/v1/snapshot/schema", params={"after": "nonsense"}, headers=headers
    )
    assert reply.status_code == 422


def test_an_authority_with_drives_does_not_hand_out_upload_targets(serving):
    """Without `direct_files` the routes exist and say so (501), so a device
    streams the bytes instead; `hello` never offered it."""
    client, headers = serving
    sha = "ab" * 32
    hello = client.get("/api/sync/v1/hello", headers=headers).json()
    assert "direct_files" not in hello["capabilities"]
    answer = client.post(
        f"/api/sync/v1/files/{sha}/upload", json={"size": 3}, headers=headers
    )
    assert answer.status_code == 501
    done = client.post(
        f"/api/sync/v1/files/{sha}/complete", json={"size": 3}, headers=headers
    )
    assert done.status_code == 501
    assert (
        client.post(
            "/api/sync/v1/files/nonsense/upload", json={"size": 3}, headers=headers
        ).status_code
        == 422
    )
