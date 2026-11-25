"""Changes to different kinds of thing made at once on two devices: what the
authority ends up holding is still a project one machine could hold, and the
device whose change could not go in is told why.

Device A changes the structure, device B the records (or the other way round),
B reaches the authority first. The random version of all of these is
`test_invariants`; these are the cases worth reading on their own."""

from __future__ import annotations


import pytest

from civex.domain.exceptions import ValidationError
from civex.testing.peers import connect, device, snapshots


# The real "a collection only holds records of its listed schemas" rule, which
# the rest of the suite switches off (tests/conftest.py).
def setup(project, authority):
    a = device(project, authority, "a")
    a.schema_svc.create("site")
    a.schema_svc.add_field("site", "name", "string")
    a.schema_svc.add_field("site", "code", "string")
    a.schema_svc.create("visit", parent="site")
    a.schema_svc.add_field("visit", "when", "string")
    a.schema_svc.create("other")
    a.dataset_svc.create("survey")
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
    parts = [c for c in a.sync_svc.conflicts() if c.kind == "rejected"]
    assert {c.entity_type for c in parts} == {"field", "schema"}
    assert all("could not go in whole" in c.message for c in parts)
    # A keeps what it made, marked: the server's version waits (not half done).
    a.sync_svc.sync()
    mine = a.schema_svc.get("site")
    assert "ref" in [f.name for f in mine.fields]
    assert mine.display_template == "{name} ({ref})"
    # Letting one part go lets the whole go: A takes the server's version.
    a.sync_svc.resolve_conflict(parts[0].id, "theirs")
    a.commit()
    mine = a.schema_svc.get("site")
    assert (mine.display_template, [f.name for f in mine.fields]) == (
        held.display_template,
        [f.name for f in held.fields],
    )
    assert a.sync_svc.conflicts() == []


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
    a.sync_svc.sync()  # (kept as it is, marked)

    # The person sees it did not go in, and renames again: this time the
    # rename rewrites the template the server has, and goes in whole.
    a.sync_svc.resolve_conflict(a.sync_svc.conflicts()[0].id, "theirs")  # all parts
    assert a.sync_svc.conflicts() == []
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


def test_a_refused_schema_change_is_kept_and_the_servers_later_change_waits(
    project, authority
):
    a, b, _, _ = setup(project, authority)
    b.record_svc.add("survey", "site", {"name": "x", "code": "2"})
    b.commit()
    a.schema_svc.set_unique_keys("site", [["name"]])
    a.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()
    (refused,) = refusals(a)
    assert refused.kind == "rejected" and refused.schema_name == "site"
    assert set(refused.takes) == {"theirs", "retry"}
    assert a.schema_svc.get("site").unique_keys  # kept, not rolled back

    b.schema_svc.update("site", display_template="{code}")
    b.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()
    kept = a.schema_svc.get("site")
    assert kept.unique_keys and kept.display_template != "{code}"  # waits

    a.sync_svc.resolve_conflict(refused.id, "theirs")
    a.commit()
    taken = a.schema_svc.get("site")
    assert taken.unique_keys == [] and taken.display_template == "{code}"


def test_a_refused_schema_change_goes_in_when_sent_again_after_the_cause_is_gone(
    project, authority
):
    a, b, _, _ = setup(project, authority)
    dup = b.record_svc.add("survey", "site", {"name": "x", "code": "2"})
    b.commit()
    a.schema_svc.set_unique_keys("site", [["name"]])
    a.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()
    (refused,) = refusals(a)
    b.record_svc.update(str(dup.id), {"name": "y", "code": "2"})
    b.commit()
    b.sync_svc.sync()
    a.sync_svc.resolve_conflict(refused.id, "retry")
    a.commit()
    a.sync_svc.sync()
    assert authority.schema_svc.get("site").unique_keys
    assert a.sync_svc.conflicts() == []


def test_an_open_item_exempts_the_thing_from_the_convergence_check(project, authority):
    from civex.testing.convergence import differences, open_items, snapshots

    a, b, _, _ = setup(project, authority)
    b.record_svc.add("survey", "site", {"name": "x", "code": "2"})
    b.commit()
    a.schema_svc.set_unique_keys("site", [["name"]])
    a.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()
    assert differences(snapshots(authority), snapshots(a))
    assert not differences(snapshots(authority), snapshots(a), open_items(a))


def _clash_on_keys(project, authority):
    a, b, _, _ = setup(project, authority)
    b.record_svc.add("survey", "site", {"name": "x", "code": "2"})
    b.commit()
    a.schema_svc.set_unique_keys("site", [["name"]])
    a.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()
    return a, b


def test_letting_go_after_two_refusals_takes_what_the_server_holds_now(
    project, authority
):
    a, b = _clash_on_keys(project, authority)
    a.schema_svc.set_unique_keys("site", [["name"], ["name", "code"]])
    a.schema_svc.set_unique_keys("site", [["name"]])
    a.commit()
    a.sync_svc.sync()
    (refused,) = refusals(a)  # the later try replaced the first item
    a.sync_svc.resolve_conflict(refused.id, "theirs")
    a.commit()
    assert a.schema_svc.get("site").unique_keys == []
    assert refusals(a) == []


def test_letting_go_of_a_refused_create_trashes_it(project, authority):
    a, b, _, _ = setup(project, authority)
    b.schema_svc.create("dup")
    b.commit()
    a.schema_svc.create("dup")
    a.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()
    (item,) = refusals(a)
    assert a.schema_svc.get("dup") is not None  # kept while it is open
    a.sync_svc.resolve_conflict(item.id, "theirs")
    a.commit()
    assert refusals(a) == []
    # The authority never had this one: it is in the trash here, not gone.
    assert [s.id for s in a.schema_svc.list_deleted()] == [item.entity_id]


def test_letting_go_is_refused_while_another_change_to_it_is_unsent(project, authority):
    a, b = _clash_on_keys(project, authority)
    (refused,) = refusals(a)
    a.schema_svc.update("site", description="more")
    a.commit()
    with pytest.raises(ValidationError, match="Send or undo your other change"):
        a.sync_svc.resolve_conflict(refused.id, "theirs")
    assert [c.id for c in refusals(a)] == [refused.id]
    assert a.schema_svc.get("site").unique_keys  # still kept


def test_a_field_delete_the_server_refuses_is_kept_and_letting_go_restores_it(
    project, authority
):
    a, b, _, _ = setup(project, authority)
    b.schema_svc.set_unique_keys("site", [["name"]])
    b.commit()
    b.sync_svc.sync()
    a.sync_svc.sync()  # (a key can't outlive its field)
    a.schema_svc.delete_field("site", "code")
    a.schema_svc.update_field("site", "name", required=True)
    a.commit()
    b.schema_svc.add_field("site", "tag", "string")
    b.schema_svc.set_unique_keys("site", [["name", "tag"]])
    b.commit()
    b.sync_svc.sync()
    a.schema_svc.delete_field("site", "name")
    a.commit()
    a.sync_svc.sync()
    items = refusals(a)
    assert items, [(c.kind, c.entity_type) for c in a.sync_svc.conflicts()]
    assert not [c for c in a.sync_svc.conflicts() if c.kind == "not_taken"]
    assert "name" not in [f.name for f in a.schema_svc.get("site").fields]  # kept
    a.sync_svc.resolve_conflict(items[0].id, "theirs")
    a.commit()
    assert "name" in [f.name for f in a.schema_svc.get("site").fields]


def test_a_refused_schema_delete_is_kept_whole_with_the_records_it_took(
    project, authority, monkeypatch
):
    a, b, site, visit = setup(project, authority)
    real = authority.authority_svc._rules.check

    def refuse_when_a_schema_goes(touched):
        if any(kind == "schema" for kind, _ in touched):
            raise ValidationError("A rule here says the schema stays")
        real(touched)

    monkeypatch.setattr(
        authority.authority_svc._rules, "check", refuse_when_a_schema_goes
    )
    a.schema_svc.delete("site")  # takes its records with it
    a.commit()
    a.sync_svc.sync()
    kinds = {(c.kind, c.entity_type) for c in a.sync_svc.conflicts()}
    assert not {k for k in kinds if k[0] == "not_taken"}
    assert ("rejected", "schema") in kinds
    assert record(a, site.id)["deleted_at"] is not None  # kept as it was made
    assert record(authority, site.id)["deleted_at"] is None
    item = next(c for c in a.sync_svc.conflicts() if c.entity_type == "schema")
    a.sync_svc.resolve_conflict(item.id, "theirs")
    a.commit()
    assert a.sync_svc.conflicts() == []
    assert record(a, site.id)["deleted_at"] is None  # back, with its records


def test_only_a_data_refusal_of_structure_holds_the_servers_changes(project, authority):
    a, _, _, _ = setup(project, authority)
    schema = a.schema_svc.get("site").id
    for code, held in (("permission", False), ("data", True)):
        a.sync_svc._repo.add_conflict(
            kind="rejected",
            entity_type="schema",
            entity_id=schema,
            field=None,
            yours=None,
            theirs=None,
            base=None,
            theirs_actor=None,
            theirs_device=None,
            theirs_at=None,
            op_id=None,
            device_name=None,
            message="x",
            code=code,
        )
        assert (("schema", schema) in a.sync_svc._repo.dirty_entities()) is held
        for c in a.sync_svc._repo.find_open_conflicts(kind="rejected"):
            a.sync_svc._repo.resolve_conflict(c.id, "theirs")
