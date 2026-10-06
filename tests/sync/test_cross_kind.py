"""Changes to different kinds of thing made at once on two devices: what the
authority ends up holding is still a project one machine could hold, and the
device whose change could not go in is told why.

Device A changes the structure, device B the records (or the other way round),
B reaches the authority first. The random version of all of these is
`test_invariants`; these are the cases worth reading on their own."""

from __future__ import annotations

import pytest

from .peers import connect, device, snapshots


# The real "a collection only holds records of its listed schemas" rule, which
# the rest of the suite switches off (tests/conftest.py).
pytestmark = pytest.mark.usefixtures("strict_schema_lists")


def setup(project, authority):
    a = device(project, authority, "a")
    a.schema_svc.create("site")
    a.schema_svc.add_field("site", "name", "string")
    a.schema_svc.add_field("site", "code", "string")
    a.schema_svc.create("visit", parent="site")
    a.schema_svc.add_field("visit", "when", "string")
    a.schema_svc.create("other")
    a.dataset_svc.create("survey")
    a.dataset_svc.update("survey", schemas=["site", "visit", "other"])
    site = a.record_svc.add("survey", "site", {"name": "x", "code": "1"})
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


def refusals(ctx):
    return [c for c in ctx.sync_svc.conflicts() if c.kind in ("rejected", "not_taken")]


def test_an_edit_to_a_record_whose_schema_was_deleted_does_not_bring_it_back(
    project, authority
):
    a, b, site, _ = setup(project, authority)
    a.schema_svc.delete("site")
    a.commit()
    b.record_svc.update(str(site.id), {"name": "edited on b", "code": "1"})
    b.commit()
    a.sync_svc.sync()
    b.sync_svc.sync()

    assert record(authority, site.id)["deleted_at"] is not None
    (refused,) = refusals(b)
    assert "schema 'site' was deleted" in refused.message


def test_a_collection_cannot_drop_a_schema_another_device_just_added_records_of(
    project, authority
):
    a, b, _, _ = setup(project, authority)
    b.record_svc.add("survey", "other", {})
    b.commit()
    a.dataset_svc.update("survey", schemas=["site", "visit"])  # none of 'other' here
    a.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()

    listed = authority.dataset_svc.get("survey").schemas
    assert "other" in listed
    (refused,) = refusals(a)
    assert "still has records of it" in refused.message


def test_a_unique_key_is_not_set_over_a_duplicate_another_device_just_made(
    project, authority
):
    a, b, _, _ = setup(project, authority)
    b.record_svc.add("survey", "site", {"name": "x", "code": "2"})
    b.commit()
    a.schema_svc.set_unique_keys("site", [["name"]])
    a.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()

    assert authority.schema_svc.get("site").unique_keys == []
    (refused,) = refusals(a)
    assert "already share" in refused.message


def test_a_field_rename_and_the_templates_it_rewrote_go_in_together_or_not_at_all(
    project, authority
):
    a, b, _, _ = setup(project, authority)
    a.schema_svc.update("site", display_template="{name} ({code})")
    a.commit()
    a.sync_svc.sync()
    b.sync_svc.sync()

    a.schema_svc.update_field("site", "code", new_name="ref")  # rewrites the template
    a.commit()
    b.schema_svc.update("site", display_template="{name} / {code}")
    b.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()

    held = authority.schema_svc.get("site")
    assert held.display_template == "{name} / {code}"
    assert "code" in [f.name for f in held.fields]  # not renamed: not half done
    parts = [c for c in a.sync_svc.conflicts() if c.kind == "not_taken"]
    assert {c.entity_type for c in parts} == {"field", "schema"}
    assert all("could not go in whole" in c.message for c in parts)
    # A is put back where the server is, not left half way through.
    a.sync_svc.sync()
    mine = a.schema_svc.get("site")
    assert (mine.display_template, [f.name for f in mine.fields]) == (
        held.display_template,
        [f.name for f in held.fields],
    )


def test_deleting_a_tree_part_of_which_was_edited_elsewhere_keeps_all_of_it(
    project, authority
):
    a, b, site, visit = setup(project, authority)
    b.record_svc.update(str(visit.id), {"when": "june"})
    b.commit()
    b.sync_svc.sync()
    a.record_svc.delete(str(site.id))  # takes the visit with it
    a.commit()
    a.sync_svc.sync()

    assert record(authority, site.id)["deleted_at"] is None
    assert record(authority, visit.id)["deleted_at"] is None
    # A is told, and is given back what was kept.
    assert {c.kind for c in a.sync_svc.conflicts()} == {"edit_vs_delete"}
    a.sync_svc.sync()
    assert record(a, site.id)["deleted_at"] is None
    assert record(a, visit.id)["deleted_at"] is None


def test_a_schema_delete_puts_each_record_it_took_in_history_and_the_feed(
    project, authority
):
    a, b, site, _ = setup(project, authority)
    b.record_svc.add("survey", "site", {"name": "made on b", "code": "9"})
    b.commit()
    b.sync_svc.sync()
    a.schema_svc.delete("site")  # A has not seen B's record
    a.commit()
    a.sync_svc.sync()
    b.sync_svc.sync()

    held = {r["id"]: r["deleted_at"] for r in snapshots(authority)["record"]}
    for ctx in (a, b):
        mine = {r["id"]: r["deleted_at"] for r in snapshots(ctx)["record"]}
        assert mine == held  # every copy, the same records deleted, same stamps
    live = [
        r
        for r in snapshots(authority)["record"]
        if r["schema_id"]
        == str(authority.schema_svc.get_by_id(site.schema_id, True).id)
        and not r["deleted_at"]
    ]
    assert live == []


def test_an_action_that_did_not_go_in_is_done_again_on_what_is_there_now(
    project, authority
):
    a, b, _, _ = setup(project, authority)
    a.schema_svc.update("site", display_template="{name} ({code})")
    a.commit()
    a.sync_svc.sync()
    b.sync_svc.sync()
    a.schema_svc.update_field("site", "code", new_name="ref")
    a.commit()
    b.schema_svc.update("site", display_template="{name} / {code}")
    b.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()
    a.sync_svc.sync()  # back where the server is

    # The person sees it did not go in, and renames again: this time the
    # rename rewrites the template the server has, and goes in whole.
    for c in a.sync_svc.conflicts():
        a.sync_svc.resolve_conflict(c.id, "theirs")
    a.schema_svc.update_field("site", "code", new_name="ref")
    a.commit()
    a.sync_svc.sync()

    held = authority.schema_svc.get("site")
    assert "ref" in [f.name for f in held.fields]
    assert held.display_template == "{name} / {ref}"


def test_a_record_is_not_deleted_from_under_a_child_added_elsewhere_meanwhile(
    project, authority
):
    a, b, site, _ = setup(project, authority)
    new = b.record_svc.add(
        "survey", "visit", {"when": "july"}, parent_record_id=str(site.id)
    )
    b.commit()
    b.sync_svc.sync()
    a.record_svc.delete(str(site.id))  # A has not seen B's new visit
    a.commit()
    a.sync_svc.sync()

    assert record(authority, site.id)["deleted_at"] is None
    assert record(authority, new.id)["deleted_at"] is None
    (kept,) = {c.message for c in a.sync_svc.conflicts() if c.entity_id == site.id}
    assert "added beneath it" in kept
