"""A record moved to another collection syncs as the one action it is: the
authority takes the tree whole, a device applies it whole (or holds it whole
while it has an unsent change to any part of it), and a move the authority
can't place any more is refused whole."""

from __future__ import annotations

from civex.testing.peers import connect, device


def setup(project, authority):
    a = device(project, authority, "a")
    a.schema_svc.create("site")
    a.schema_svc.add_field("site", "name", "string")
    a.schema_svc.create("visit", parent="site")
    a.schema_svc.add_field("visit", "when", "string")
    a.dataset_svc.create("survey")
    a.dataset_svc.create("archive")
    site = a.record_svc.add("survey", "site", {"name": "x"})
    visit = a.record_svc.add(
        "survey", "visit", {"when": "may"}, parent_record_id=str(site.id)
    )
    a.commit()
    connect(a)
    b = device(project, authority, "b")
    connect(b)
    return a, b, site, visit


def record(ctx, rid):
    return ctx.sync_repo.snapshot("record", rid)


def collection(ctx, name):
    return str(ctx.dataset_svc.get(name).id)


def test_a_move_reaches_the_authority_and_every_device_whole(project, authority):
    a, b, site, visit = setup(project, authority)
    a.record_svc.move("archive", ids=[str(site.id)])
    a.commit()
    a.sync_svc.sync()
    b.sync_svc.sync()

    for ctx in (authority, b):
        archive = collection(ctx, "archive")
        assert record(ctx, site.id)["dataset_id"] == archive
        assert record(ctx, visit.id)["dataset_id"] == archive
        assert record(ctx, visit.id)["parent_record_id"] == str(site.id)
    assert b.sync_svc.conflicts() == []


def test_a_device_with_an_unsent_edit_to_a_child_holds_the_whole_move(
    project, authority
):
    a, b, site, visit = setup(project, authority)
    # b edits the visit and does not sync yet.
    b.record_svc.update(str(visit.id), {"when": "june"})
    b.commit()
    # a moves the tree; b pulls it while its own edit is unsent.
    a.record_svc.move("archive", ids=[str(site.id)])
    a.commit()
    a.sync_svc.sync()

    b.sync_svc._pull(b.sync_svc._transport())  # the feed only, no push
    b.commit()
    # Neither record moved: a child in another collection than its parent
    # is not a project, so the whole action waits for the push.
    survey = collection(b, "survey")
    assert record(b, site.id)["dataset_id"] == survey
    assert record(b, visit.id)["dataset_id"] == survey

    b.sync_svc.sync()
    archive = collection(b, "archive")
    assert record(b, site.id)["dataset_id"] == archive
    assert record(b, visit.id)["dataset_id"] == archive
    # The edit went in too: it was to another field than the move changed.
    assert record(authority, visit.id)["data"] == record(b, visit.id)["data"]
    assert "june" in record(authority, visit.id)["data"].values()


def test_a_move_under_a_record_that_moved_elsewhere_meanwhile_follows_it(
    project, authority
):
    a, b, site, visit = setup(project, authority)
    other = a.record_svc.add("archive", "site", {"name": "y"})
    a.commit()
    a.sync_svc.sync()
    b.sync_svc.sync()
    a.dataset_svc.create("third")
    a.commit()
    # b moves the visit under `other` in archive; a moves `other` to a third
    # collection first.
    b.record_svc.move("archive", str(other.id), ids=[str(visit.id)])
    b.commit()
    a.record_svc.move("third", ids=[str(other.id)])
    a.commit()
    a.sync_svc.sync()
    b.sync_svc.sync()

    # A child's collection is its parent's: the visit went under `other`,
    # where `other` is now, and every copy says so.
    third = collection(authority, "third")
    assert record(authority, visit.id)["dataset_id"] == third
    assert record(authority, visit.id)["parent_record_id"] == str(other.id)
    assert record(b, visit.id)["dataset_id"] == collection(b, "third")
    assert record(b, visit.id)["parent_record_id"] == str(other.id)
    assert not b.sync_svc.conflicts()
