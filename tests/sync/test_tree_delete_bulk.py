"""A pushed delete of whole trees (one action each) goes in with the bulk path,
and writes exactly what settling each action whole writes: the same answers,
the same history (one action per tree, in order) and the same records."""

from __future__ import annotations

from .test_bulk_changes import Flow
from .test_bulk_push import send


def _trees(f: Flow, n: int, kids: int):
    roots = []
    for i in range(n):
        p = f.make("mine", "encounter", {"site": f"s{i}", "depth": 1.0})
        roots.append(p)
        for k in range(kids):
            f.make("mine", "recording", {"label": f"k{i}-{k}", "must": "m"}, str(p))
    return roots


def _run(project, bulk: bool):
    def named(name):
        return project(f"{name}-{bulk}")

    ctx = named("authority")
    ctx.authority_svc._bulk = bulk
    f = Flow(named)
    roots = _trees(f, 4, 3)
    send(ctx, f.structure + f.take())
    gone = f.deleted(roots)
    calls = {"whole": 0}
    real = ctx.authority_svc._settle_action

    def counted(who, action):
        calls["whole"] += 1
        return real(who, action)

    ctx.authority_svc._settle_action = counted
    answers, _ = send(ctx, gone)
    return gone, answers, calls["whole"]


def test_whole_tree_deletes_go_in_bulk_and_match_the_whole_settle(project):
    gone, bulk, whole_calls = _run(project, True)
    assert whole_calls == 0  # nothing needed settling one action at a time
    _, one_by_one, whole_calls2 = _run(project, False)
    assert whole_calls2 == 4
    assert [a[1] for a in bulk] == ["applied"] * len(gone)
    assert [a[1:4] for a in bulk] == [a[1:4] for a in one_by_one]
    # entries numbered in the order sent, each its own number
    assert [a[4] for a in bulk] == sorted(a[4] for a in bulk)
    assert len({a[4] for a in bulk}) == len(bulk)


def test_a_record_added_beneath_a_tree_here_keeps_the_tree(project):
    ctx = project("authority")
    f = Flow(project)
    roots = _trees(f, 2, 2)
    send(ctx, f.structure + f.take())
    gone = f.deleted(roots)
    # a record beneath the first tree, made here after the device last looked
    late = ctx.record_svc.add(
        "mine", "recording", {"label": "late", "must": "m"}, parent_record_id=str(roots[0])
    )
    ctx.commit()
    answers, _ = send(ctx, gone)
    by_root = {a[0]: a for a in answers}
    first = [by_root[e.id] for e in gone if e.op == gone[0].op]
    assert all(a[1] == "conflict" for a in first)
    assert ctx.record_svc.get(str(late.id)).deleted_at is None
    assert ctx.record_svc.get(str(roots[0])).deleted_at is None
