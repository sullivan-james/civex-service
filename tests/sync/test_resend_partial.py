"""An action sent again of which only some entries were answered (a page split,
a timeout, a lost answer) is settled idempotently: what was answered is
answered again from what was stored, only the rest is applied."""

from __future__ import annotations

from .test_bulk_changes import Flow
from .test_bulk_push import send


def _tree(project):
    f = Flow(project)
    parent = f.make("mine", "encounter", {"site": "p", "depth": 1.0})
    kids = [f.make("mine", "recording", {"label": f"k{i}", "must": "m"}, str(parent)) for i in range(3)]
    return f, parent, kids


def test_resending_an_action_some_of_which_was_answered(project):
    ctx = project("authority")
    f, parent, kids = _tree(project)
    send(ctx, f.structure + f.take())
    gone = f.deleted([parent])
    assert len(gone) > 1 and len({e.op for e in gone}) == 1
    first, _ = send(ctx, gone[:2])  # only part of the action was answered
    assert len(first) == 2
    answers, _ = send(ctx, gone)  # the device sends the whole action again
    assert [a[0] for a in answers] == [e.id for e in gone]
    # the ones answered before are answered again, as they were
    assert [a[5] for a in answers[:2]] == [True, True]
    assert [a[1] for a in answers[:2]] == [a[1] for a in first]
    assert not any(a[5] for a in answers[2:])
    again, _ = send(ctx, gone)  # and a third time: all answered as before
    assert [a[:2] for a in again] == [a[:2] for a in answers]
    assert all(a[5] for a in again)
