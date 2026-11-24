"""Releases are published on a host and never synced: the scenarios of
`civex.testing.releases` against projects in folders, and what an authority
answers a device on protocol 5 or 6 that still asks about them."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from civex.config import load_config, save_config
from civex.domain.sync import (
    NOT_SYNCED_KINDS,
    PROTOCOL_MAX,
    REFUSAL_NOT_SYNCED,
    SyncEntry,
    entry_for,
    kinds_for,
)
from civex.testing import releases
from civex.testing.peers import build_study


def test_a_release_stays_where_it_was_made(project, authority):
    assert releases.stay_where_made(project, authority) == []


def test_a_release_sent_anyway_is_refused_and_not_kept(project, authority):
    assert releases.refused_when_sent(project, authority) == []


def test_the_protocol_moved_on_and_release_is_no_kind_any_more():
    assert PROTOCOL_MAX == 6
    assert NOT_SYNCED_KINDS == {"release"}
    assert all("release" not in kinds_for(p) for p in range(3, PROTOCOL_MAX + 1))


def test_a_release_entry_is_never_offered_to_any_protocol(project):
    ctx = project("p")
    build_study(ctx)
    made = ctx.release_svc.create("v1", "A release")
    ctx.commit()
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="create",
        entity_type="release",
        entity_id=made.id,
        old_data=None,
        new_data=made.to_dict(),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    assert all(entry_for(p, entry) is None for p in range(3, PROTOCOL_MAX + 1))
    # And what this computer would send leaves it out.
    assert "release" not in {e.entity_type for e in ctx.sync_repo.pending_entries(100)}
    assert ctx.sync_repo.count_pending() == len(ctx.sync_repo.pending_entries(100))


@pytest.fixture()
def serving(ctx, client, sign_in_over_http):
    config = load_config()
    config.sync.serve = True
    save_config(config)
    _, invite = ctx.device_keys.invite("laptop")
    ctx.commit()
    token = sign_in_over_http(client, invite)

    def headers(protocol: int) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "X-Civex-Protocol": str(protocol)}

    return client, headers


def test_a_protocol_5_device_sending_a_release_is_refused_with_its_code(serving, ctx):
    client, headers = serving
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="create",
        entity_type="release",
        entity_id=uuid.uuid4(),
        old_data=None,
        new_data={"id": "x"},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    reply = client.post(
        "/api/sync/v1/push", json={"entries": [entry.to_dict()]}, headers=headers(5)
    )
    assert reply.status_code == 200, reply.text
    (result,) = reply.json()["results"]
    assert result["status"] == "rejected"
    assert [c["code"] for c in result["conflicts"]] == [REFUSAL_NOT_SYNCED]
    assert "published on a civex hub" in result["message"]
    assert ctx.release_svc.list_all() == []


def test_the_feed_and_hello_leave_releases_out(serving, ctx):
    client, headers = serving
    build_study(ctx)
    ctx.release_svc.create("v1", "A release")
    ctx.commit()
    for protocol in (5, PROTOCOL_MAX):
        feed = client.get("/api/sync/v1/feed?after=0", headers=headers(protocol))
        assert feed.status_code == 200, feed.text
        kinds = {e["entity_type"] for e in feed.json()["entries"]}
        assert kinds and "release" not in kinds
        hello = client.get("/api/sync/v1/hello", headers=headers(protocol)).json()
        assert "release" not in hello["counts"]


def test_a_protocol_5_device_joining_gets_an_empty_release_snapshot(serving, ctx):
    client, headers = serving
    build_study(ctx)
    ctx.release_svc.create("v1", "A release")
    ctx.commit()
    old = client.get("/api/sync/v1/snapshot/release", headers=headers(5))
    assert old.status_code == 200, old.text
    assert old.json()["items"] == [] and old.json()["more"] is False
    # A device on the current protocol was never told there is such a kind.
    new = client.get("/api/sync/v1/snapshot/release", headers=headers(PROTOCOL_MAX))
    assert new.status_code == 422
