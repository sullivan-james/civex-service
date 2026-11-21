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


def test_a_device_asks_to_join_over_http_and_is_let_in_by_the_admin(serving, ctx):
    """The two unauthenticated routes of the device-login flow, and the admin's
    approval through the people-facing API."""
    import uuid

    from civex import keys

    client, headers = serving
    plain = {"X-Civex-Protocol": headers["X-Civex-Protocol"]}
    private = keys.new_private_key()
    body = {"device_id": str(uuid.uuid4()), "public_key": keys.public_of(private)}
    asked = client.post("/api/sync/v1/device-login", headers=plain, json=body)
    assert asked.status_code == 200, asked.text
    started = asked.json()
    assert started["verify_url"] is None and started["interval"] >= 1
    hello = client.get("/api/sync/v1/hello", headers=headers).json()
    assert "device_login" in hello["capabilities"]

    poll = f"/api/sync/v1/device-login/{started['device_code']}"
    assert client.get(poll, headers=plain).status_code == 202
    waiting = client.get("/api/remote/authority").json()["logins"]
    assert [w["code"] for w in waiting] == [started["user_code"]]
    assert waiting[0]["fingerprint"] == keys.fingerprint(body["public_key"])

    approved = client.post(
        f"/api/remote/authority/logins/{started['user_code']}/approve",
        json={"name": "tablet"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["logins"] == []
    assert "tablet" in [d["name"] for d in approved.json()["devices"]]
    joined = client.get(poll, headers=plain)
    assert joined.status_code == 200 and joined.json()["device_name"] == "tablet"

    # Denied: the device is told so, once.
    other = client.post(
        "/api/sync/v1/device-login",
        headers=plain,
        json={
            "device_id": str(uuid.uuid4()),
            "public_key": keys.public_of(keys.new_private_key()),
        },
    ).json()
    denied = client.post(f"/api/remote/authority/logins/{other['user_code']}/deny")
    assert denied.status_code == 200
    assert (
        client.get(
            f"/api/sync/v1/device-login/{other['device_code']}", headers=plain
        ).status_code
        == 410
    )
    assert (
        client.post(
            f"/api/remote/authority/logins/{other['user_code']}/deny"
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/remote/authority/logins/{other['user_code']}/approve",
            json={"name": "x"},
        ).status_code
        == 422
    )


def test_a_device_on_the_previous_protocol_is_served_what_it_can_read(serving, ctx):
    """Protocol 4 added the Analytics page and a kind's charts; a device on 3
    still syncs: it is never sent a page entry (a run of them is read past)
    nor a kind's charts, and can't ask for the page's snapshot."""
    client, headers = serving
    ctx.schema_svc.create("sample")
    ctx.schema_svc.add_field("sample", "site", "string")
    ctx.view_svc.create("sample", "by site")
    ctx.schema_svc.set_charts("sample", [{"id": "a", "group_by": ["site"]}])
    ctx.commit()
    ctx.view_svc.update("sample", "by site", columns=["site"])
    for size in ("wide", "small", "wide"):
        ctx.dashboard_svc.add(chart={"group_by": ["site"]}, schema="sample", size=size)
    ctx.commit()
    old = {**headers, "X-Civex-Protocol": "3"}

    feed = client.get("/api/sync/v1/feed", params={"limit": 2}, headers=old).json()
    kinds = [e["entity_type"] for e in feed["entries"]]
    assert "dashboard" not in kinds and kinds
    every = client.get("/api/sync/v1/feed", params={"limit": 500}, headers=old).json()
    assert {e["entity_type"] for e in every["entries"]} == {"schema", "field", "view"}
    for e in every["entries"]:
        assert "charts" not in (e.get("new_data") or {})
        assert "charts" not in (e.get("old_data") or {})
        assert not any(k.startswith("charts") for k in e.get("delta") or {})
    # Past the view, only page entries are left: read past, nothing sent.
    view_seq = max(e["hub_seq"] for e in every["entries"])
    rest = client.get(
        "/api/sync/v1/feed", params={"after": view_seq, "limit": 1}, headers=old
    ).json()
    assert rest["entries"] == [] and rest["more"] is False

    schemas = client.get("/api/sync/v1/snapshot/schema", headers=old).json()
    assert "charts" not in schemas["items"][0]
    page = client.get("/api/sync/v1/snapshot/dashboard", headers=old)
    assert page.status_code == 422

    # On the current protocol, all of it.
    now = client.get("/api/sync/v1/feed", params={"limit": 500}, headers=headers)
    assert "dashboard" in {e["entity_type"] for e in now.json()["entries"]}
    assert client.get("/api/sync/v1/snapshot/dashboard", headers=headers).json()[
        "items"
    ]
