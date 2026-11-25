"""Several trees deleted (or restored) in one call are one action per tree: each
goes in whole, never half-applied. Also for a device that logged them level by
level (parent 1, parent 2, child 1, child 2), as older ones did."""

from __future__ import annotations

import os

import pytest

from civex.services import record_service
from civex.testing.peers import connect, device

from .test_postgres_authority import pg_authority  # noqa: F401  (fixture)

_PG = os.environ.get("CIVEX_TEST_POSTGRES_URL")


@pytest.fixture(params=["sqlite", "postgres"])
def server(request):
    if request.param == "sqlite":
        return request.getfixturevalue("authority")
    if not _PG:
        pytest.skip("CIVEX_TEST_POSTGRES_URL not set")
    return request.getfixturevalue("pg_authority")


@pytest.fixture(params=["grouped", "old_client"])
def levelwise(request, monkeypatch):
    """`old_client`: the device logs a call's entries in level order."""
    if request.param == "old_client":
        monkeypatch.setattr(record_service, "_by_tree", lambda ids, ops: ids)
    return request.param


def _study(project, server, trees=2, children=2):
    laptop = device(project, server, "laptop")
    laptop.schema_svc.create("encounter")
    laptop.schema_svc.add_field("encounter", "site", "string")
    laptop.schema_svc.create("recording", parent="encounter")
    laptop.schema_svc.add_field("recording", "label", "string")
    laptop.dataset_svc.create("study")
    laptop.commit()
    connect(laptop)
    parents, everyone = [], []
    for i in range(trees):
        p = laptop.record_svc.add("study", "encounter", {"site": f"s{i}"})
        parents.append(str(p.id))
        everyone.append(str(p.id))
        for k in range(children):
            c = laptop.record_svc.add(
                "study",
                "recording",
                {"label": f"r{i}{k}"},
                parent_record_id=str(p.id),
            )
            everyone.append(str(c.id))
    laptop.commit()
    laptop.sync_svc.sync()
    return laptop, parents, everyone


def _gone(ctx, ids):
    import uuid

    rows = ctx.record_svc._records.list_by_ids([uuid.UUID(i) for i in ids])
    assert len(rows) == len(ids)
    return [bool(r.deleted_at) for r in rows]


def _conflicts(report):
    return getattr(report, "conflicts", 0)


def test_deleting_several_trees_at_once_goes_in_whole(project, server, levelwise):
    laptop, parents, everyone = _study(project, server)
    laptop.record_svc.delete_many(parents)
    laptop.commit()
    report = laptop.sync_svc.sync()
    assert _conflicts(report) == 0
    assert all(_gone(server, everyone))
    assert all(_gone(laptop, everyone))
    assert laptop.sync_svc.sync() is not None
    assert all(_gone(laptop, everyone))


def test_restoring_several_trees_at_once_goes_in_whole(project, server, levelwise):
    laptop, parents, everyone = _study(project, server)
    laptop.record_svc.delete_many(parents)
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.record_svc.restore_records(everyone)
    laptop.commit()
    report = laptop.sync_svc.sync()
    assert _conflicts(report) == 0
    assert not any(_gone(server, everyone))
    assert not any(_gone(laptop, everyone))


def test_an_interleaved_push_is_applied_whole_per_tree(project, server):
    """What an older device sent: parent 1, parent 2, child 1, child 2 ..."""
    from civex.testing import principal, statuses

    laptop, parents, everyone = _study(project, server)
    laptop.record_svc.delete_many(parents)
    laptop.commit()
    entries = laptop.sync_svc._repo.pending_entries(100)
    trees: dict = {}
    for e in entries:
        trees.setdefault(e.op, []).append(e)
    assert len(trees) == 2 and all(len(t) == 3 for t in trees.values())
    first, second = trees.values()
    by_level = [first[0], second[0], *first[1:], *second[1:]]
    result = server.authority_svc.push(principal(server, "laptop"), by_level)
    server.commit()
    assert statuses(result) == ["applied"] * 6
    # answered per tree, trees in the order first met
    assert [r.op_id for r in result.results] == [e.id for e in first + second]
    assert all(_gone(server, everyone))
