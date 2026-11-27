"""An action sent again of which only some entries were answered (a page split,
a timeout, a lost answer) is settled idempotently: what was answered is
answered again from what was stored, only the rest is applied."""

from __future__ import annotations

import pytest

from civex.domain.exceptions import NotFoundError

from .test_bulk_changes import Flow
from .test_bulk_push import send


def _tree(project):
    f = Flow(project)
    parent = f.make("mine", "encounter", {"site": "p", "depth": 1.0})
    kids = [
        f.make("mine", "recording", {"label": f"k{i}", "must": "m"}, str(parent))
        for i in range(3)
    ]
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
    assert [a[1] for a in answers] == ["conflict"] * len(gone)
    assert not any(a[5] for a in answers[2:])
    again, _ = send(ctx, gone)  # and a third time: all answered as before
    assert [a[:2] for a in again] == [a[:2] for a in answers]
    assert all(a[5] for a in again)


def test_a_refused_action_resent_in_part_stays_refused_whole(project):
    ctx = project("authority")
    f, parent, kids = _tree(project)
    send(ctx, f.structure + f.take())
    gone = f.deleted([parent])
    first, _ = send(ctx, gone[:2])  # the rest of the tree is live: not whole
    assert [a[1] for a in first] == ["conflict"] * 2
    answers, _ = send(ctx, gone)
    assert [a[1] for a in answers] == ["conflict"] * len(gone)
    # nothing is half done: the parent and every child are still here
    for rid in [parent, *kids]:
        assert ctx.record_svc.get(str(rid)).deleted_at is None


def test_an_applied_part_resent_with_the_rest_settles_only_the_rest(project):
    ctx = project("authority")
    f, parent, kids = _tree(project)
    send(ctx, f.structure + f.take())
    gone = f.deleted([parent])
    leaves = [e for e in gone if e.entity_id in kids]  # one action's own entries
    assert len(leaves) == 3
    first, _ = send(ctx, leaves[:1])
    assert [a[1] for a in first] == ["applied"]
    answers, _ = send(ctx, leaves)
    assert [a[0] for a in answers] == [e.id for e in leaves]
    assert [a[1] for a in answers] == ["applied"] * 3
    assert [a[5] for a in answers] == [True, False, False]
    for rid in kids:
        with pytest.raises(NotFoundError):  # deleted
            ctx.record_svc.get(str(rid))
