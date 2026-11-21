"""Review status and notes travel between devices: the scenarios of
`civex.testing.review`, run against projects in folders, and what a device on
the previous protocol is sent."""

from __future__ import annotations

from civex.domain.sync import entry_for, kinds_for, snapshot_for

from civex.testing import review
from civex.testing.peers import build_study


def test_a_review_and_a_note_travel(project, authority):
    assert review.travels(project, authority) == []


def test_two_reviews_at_once_settle_on_the_later_without_a_conflict(project, authority):
    assert review.marked_at_once(project, authority) == []


def test_a_device_on_the_previous_protocol_gets_neither(project):
    ctx = project("p")
    record = build_study(ctx)
    ctx.record_svc.set_review("checked", ids=[str(record.id)])
    ctx.note_svc.add(str(record.id), "looks fine")
    ctx.commit()
    entries = [e.on_the_wire() for e in ctx.sync_repo.pending_entries(100)]
    old = [e for entry in entries if (e := entry_for(3, entry)) is not None]

    assert "note" not in kinds_for(3)
    assert "note" not in {e.entity_type for e in old}
    for e in old:
        for side in (e.old_data, e.new_data):
            assert "review" not in (side or {})
        assert not any(p.startswith("review") for p in e.delta or {})
    (snap,) = ctx.sync_repo.snapshots_page("record", None, 10)
    assert snap["review"]["status"] == "checked"
    assert "review" not in snapshot_for(3, "record", snap)
    assert [entry_for(4, e) for e in entries] == entries
