"""Releases travel between devices: the scenarios of `civex.testing.releases`,
run against projects in folders, and what a device on the previous protocol
is sent."""

from __future__ import annotations

from civex.domain.sync import entry_for, kinds_for

from civex.testing import releases
from civex.testing.peers import build_study


def test_a_release_and_its_bundle_travel(project, authority):
    assert releases.travels(project, authority) == []


def test_a_release_content_can_not_be_changed_over_sync(project, authority):
    assert releases.content_is_fixed(project, authority) == []


def test_a_device_on_the_previous_protocol_is_not_sent_releases(project):
    ctx = project("p")
    build_study(ctx)
    ctx.release_svc.create("v1", "A release")
    ctx.commit()
    entries = [e.on_the_wire() for e in ctx.sync_repo.pending_entries(100)]
    assert "release" not in kinds_for(3)
    assert "release" in {e.entity_type for e in entries}
    assert all(
        e.entity_type != "release"
        for entry in entries
        if (e := entry_for(3, entry)) is not None
    )
    (sent,) = [e for e in entries if e.entity_type == "release"]
    assert "local_seq" not in (sent.new_data or {})
