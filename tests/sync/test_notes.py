"""Notes and their threads travel between devices: the scenarios of
`civex.testing.notes`, run against projects in folders, and what a device on
the previous protocol is sent."""

from __future__ import annotations

from civex.domain.sync import entry_for, kinds_for

from civex.testing import notes
from civex.testing.peers import build_study


def test_a_note_and_its_thread_travel(project, authority):
    assert notes.travels(project, authority) == []


def test_two_replies_at_once_are_two_replies(project, authority):
    assert notes.replies_at_once(project, authority) == []


def test_a_device_on_the_previous_protocol_gets_no_notes(project):
    ctx = project("p")
    record = build_study(ctx)
    note = ctx.note_svc.add(str(record.id), "looks fine")
    ctx.note_svc.reply(str(note.id), "agreed")
    ctx.commit()
    entries = [e.on_the_wire() for e in ctx.sync_repo.pending_entries(100)]
    old = [e for entry in entries if (e := entry_for(3, entry)) is not None]

    assert "note" not in kinds_for(3)
    assert "note" not in {e.entity_type for e in old}
    assert [entry_for(4, e) for e in entries] == entries
