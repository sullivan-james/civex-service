"""Reviewing what did not go in as made: what a row says, and how it is settled."""

from __future__ import annotations

import pytest

from civex.domain.exceptions import ConflictMovedError, ValidationError


def data(ctx, record):
    return ctx.record_svc.get(str(record.id)).data


def clash(laptop, phone, record):
    """Both edit `site`; the laptop gets there first, so the phone's is kept for
    review. Returns the phone's one open conflict."""
    laptop.record_svc.update(str(record.id), {"site": "laptop", "depth": 1.0})
    phone.record_svc.update(str(record.id), {"site": "phone", "depth": 1.0})
    laptop.commit()
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    (conflict,) = phone.sync_svc.conflicts()
    return conflict


# -- what a row says ---------------------------------------------------------------


def test_a_conflict_says_what_it_was_who_changed_it_and_which_record_and_field(pair):
    laptop, phone, record = pair

    c = clash(laptop, phone, record)

    assert (c.base, c.theirs, c.yours) == ("x", "laptop", "phone")
    assert c.theirs_actor == "laptop" and c.theirs_at
    assert c.field_label.lower() == "site" and c.dtype == "string"
    assert c.record_name and c.dataset_name == "study" and c.schema_name == "encounter"
    assert c.current == "laptop" and c.stale is False


def test_a_conflict_is_stale_once_the_value_has_changed_again(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)

    laptop.record_svc.update(str(record.id), {"site": "laptop again", "depth": 1.0})
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    (c,) = phone.sync_svc.conflicts()
    assert c.stale is True and c.current == "laptop again"


def test_the_authority_keeps_no_list_of_conflicts(pair, authority):
    laptop, phone, record = pair
    clash(laptop, phone, record)

    assert authority.sync_svc.conflicts() == []


# -- putting a value back ----------------------------------------------------------


def test_using_mine_is_an_ordinary_checked_edit(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)

    phone.sync_svc.resolve_conflict(c.id, "mine")

    assert data(phone, record) == {"site": "phone", "depth": 1.0}  # other field kept
    entry = phone.history_svc.page(limit=1)[0]
    assert entry.action == "update" and entry.entity_id == record.id
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    assert data(laptop, record)["site"] == "phone"


def test_using_mine_is_refused_when_the_value_has_moved_on_unless_forced(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)
    laptop.record_svc.update(str(record.id), {"site": "newer", "depth": 1.0})
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    with pytest.raises(ConflictMovedError) as moved:
        phone.sync_svc.resolve_conflict(c.id, "mine")

    assert moved.value.current == "newer"
    assert data(phone, record)["site"] == "newer"  # nothing was overwritten
    assert phone.sync_svc.status().open_conflicts == 1
    phone.sync_svc.resolve_conflict(c.id, "mine", force=True)
    assert data(phone, record)["site"] == "phone"


def test_a_value_of_your_own_can_be_put_back_instead(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)

    phone.sync_svc.resolve_conflict(c.id, "value", value="both")

    assert data(phone, record)["site"] == "both"
    assert phone.sync_svc.conflicts() == []


def test_a_value_the_record_would_refuse_is_refused_and_the_conflict_stays_open(
    project, authority
):
    from .peers import build_study, connect, device

    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    laptop.schema_svc.add_field(
        "encounter", "rank", "integer", restrictions={"min": 0, "max": 5}
    )
    laptop.record_svc.update(str(record.id), {"site": "x", "depth": 1.0, "rank": 1})
    laptop.commit()
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    laptop.record_svc.update(str(record.id), {"site": "x", "depth": 1.0, "rank": 2})
    phone.record_svc.update(str(record.id), {"site": "x", "depth": 1.0, "rank": 3})
    laptop.commit()
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    (c,) = phone.sync_svc.conflicts()

    with pytest.raises(ValidationError):
        phone.sync_svc.resolve_conflict(c.id, "value", value=99)

    assert phone.sync_svc.status().open_conflicts == 1


def test_keeping_theirs_changes_nothing(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)
    before = phone.history_svc.page(limit=1)[0].id

    phone.sync_svc.resolve_conflict(c.id, "theirs")

    assert data(phone, record)["site"] == "laptop"
    assert phone.history_svc.page(limit=1)[0].id == before


# -- a record deleted on the other side ------------------------------------------------


def delete_vs_edit(laptop, phone, record):
    laptop.record_svc.delete(str(record.id))
    phone.record_svc.update(str(record.id), {"site": "edited", "depth": 1.0})
    laptop.commit()
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    return next(c for c in phone.sync_svc.conflicts() if c.kind == "edit_vs_delete")


def test_an_edit_to_a_record_deleted_elsewhere_can_keep_it_or_delete_it(pair):
    laptop, phone, record = pair
    c = delete_vs_edit(laptop, phone, record)

    assert c.theirs_actor == "laptop"
    with pytest.raises(ValidationError):
        phone.sync_svc.resolve_conflict(c.id, "mine")  # not a thing to do here
    phone.sync_svc.resolve_conflict(c.id, "delete")
    assert phone.record_svc.list_deleted()  # it is deleted here now
    assert phone.sync_svc.conflicts() == []


# -- a refused change, sent again -----------------------------------------------------


def test_a_refused_new_record_can_be_fixed_and_sent_again(pair, authority):
    laptop, phone, record = pair
    laptop.schema_svc.set_unique_keys("encounter", [["site"]])
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    # Neither has seen the other's new record, so each may add a "z".
    laptop.record_svc.add("study", "encounter", {"site": "z", "depth": 1.0})
    mine = phone.record_svc.add("study", "encounter", {"site": "z", "depth": 2.0})
    laptop.commit()
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    (refused,) = [c for c in phone.sync_svc.conflicts() if c.kind == "rejected"]
    assert authority.sync_repo.snapshot("record", mine.id) is None

    phone.record_svc.update(str(mine.id), {"site": "z2", "depth": 2.0})
    phone.commit()
    phone.sync_svc.resolve_conflict(refused.id, "retry")
    phone.sync_svc.sync()
    laptop.sync_svc.sync()

    held = authority.sync_repo.snapshot("record", mine.id)
    assert held is not None and "z2" in held["data"].values()
    assert data(laptop, mine)["site"] == "z2"


def test_a_refused_change_that_no_longer_exists_here_cannot_be_sent(pair):
    laptop, phone, record = pair
    laptop.schema_svc.set_unique_keys("encounter", [["site"]])
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    laptop.record_svc.add("study", "encounter", {"site": "z", "depth": 1.0})
    mine = phone.record_svc.add("study", "encounter", {"site": "z", "depth": 2.0})
    laptop.commit()
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    (refused,) = [c for c in phone.sync_svc.conflicts() if c.kind == "rejected"]
    phone.record_svc.delete(str(mine.id))
    phone.record_svc.purge(str(mine.id))
    phone.commit()

    with pytest.raises(ValidationError, match="no longer exists"):
        phone.sync_svc.resolve_conflict(refused.id, "retry")


# -- what a row offers ------------------------------------------------------------


def test_a_row_says_what_can_be_done_and_what_else_of_the_edit_was_saved(pair):
    laptop, phone, record = pair
    laptop.record_svc.update(str(record.id), {"site": "laptop", "depth": 1.0})
    phone.record_svc.update(str(record.id), {"site": "phone", "depth": 7.0})
    laptop.commit()
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    (c,) = phone.sync_svc.conflicts()

    assert c.takes == ["theirs", "mine", "value"]
    # The same edit also set depth, which did go in: nothing else of it was lost.
    assert [(a["field_label"].lower(), a["value"]) for a in c.also_saved] == [
        ("depth", 7.0)
    ]


# -- settling many at once --------------------------------------------------------


def two_kinds(laptop, phone, record):
    """A clash on one record and a refused new record: two open conflicts."""
    laptop.schema_svc.set_unique_keys("encounter", [["site"]])
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    laptop.record_svc.update(str(record.id), {"site": "laptop", "depth": 1.0})
    phone.record_svc.update(str(record.id), {"site": "phone", "depth": 1.0})
    laptop.record_svc.add("study", "encounter", {"site": "z", "depth": 1.0})
    phone.record_svc.add("study", "encounter", {"site": "z", "depth": 2.0})
    for ctx in (laptop, phone):
        ctx.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    return {c.kind for c in phone.sync_svc.conflicts()}


def test_keeping_theirs_for_everything_settles_every_kind_at_once(pair):
    laptop, phone, record = pair
    assert two_kinds(laptop, phone, record) == {"conflict", "rejected"}

    report = phone.sync_svc.resolve_many("theirs")

    assert (report.done, report.not_offered, report.failed) == (2, 0, [])
    assert len(report.settled) == 2
    assert phone.sync_svc.conflicts() == []
    assert data(phone, record)["site"] == "laptop"


def test_settling_many_can_be_narrowed_by_kind_and_by_record(pair):
    laptop, phone, record = pair
    two_kinds(laptop, phone, record)

    assert phone.sync_svc.resolve_many("theirs", kind="rejected").done == 1
    assert {c.kind for c in phone.sync_svc.conflicts()} == {"conflict"}
    other = phone.record_svc.add("study", "encounter", {"site": "q", "depth": 1.0})
    assert phone.sync_svc.resolve_many("theirs", entity_id=other.id).done == 0
    assert phone.sync_svc.resolve_many("theirs", entity_id=record.id).done == 1


def test_a_dry_run_only_counts(pair):
    laptop, phone, record = pair
    two_kinds(laptop, phone, record)

    assert phone.sync_svc.resolve_many("theirs", dry_run=True).done == 2
    assert len(phone.sync_svc.conflicts()) == 2


def test_those_that_do_not_offer_a_way_stay_open_and_are_counted(pair):
    laptop, phone, record = pair
    two_kinds(laptop, phone, record)

    # A refused change can't be "put back as mine"; the clash can.
    report = phone.sync_svc.resolve_many("mine")

    assert (report.done, report.not_offered) == (1, 1)
    assert [c.kind for c in phone.sync_svc.conflicts()] == ["rejected"]


def test_one_that_fails_its_checks_stays_open_and_the_rest_still_go(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)
    laptop.record_svc.update(str(record.id), {"site": "again", "depth": 1.0})
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()  # the value moved on since the conflict was recorded

    report = phone.sync_svc.resolve_many("mine")

    assert report.done == 0 and [i for i, _ in report.failed] == [c.id]
    assert len(phone.sync_svc.conflicts()) == 1
    assert phone.sync_svc.resolve_many("mine", force=True).done == 1


def test_settling_all_reaches_past_the_first_page(pair):
    laptop, phone, record = pair
    import uuid

    for _ in range(205):
        phone.sync_repo.add_conflict(
            kind="rejected",
            entity_type="record",
            entity_id=uuid.uuid4(),
            field=None,
            yours={},
            theirs=None,
            base=None,
            theirs_actor=None,
            theirs_at=None,
            op_id=uuid.uuid4(),
            device_name=None,
            message="no",
        )
    phone.commit()

    assert phone.sync_svc.resolve_many("theirs", dry_run=True).done == 205
    assert phone.sync_svc.resolve_many("theirs").done == 205
    assert phone.sync_svc.status().open_conflicts == 0


def test_keeping_theirs_can_be_taken_back_but_putting_mine_back_cannot(pair):
    laptop, phone, record = pair
    kept = clash(laptop, phone, record)
    phone.sync_svc.resolve_conflict(kept.id, "theirs")

    assert phone.sync_svc.reopen_conflicts([kept.id]) == 1
    assert [c.id for c in phone.sync_svc.conflicts()] == [kept.id]

    phone.sync_svc.resolve_conflict(kept.id, "mine")
    assert phone.sync_svc.reopen_conflicts([kept.id]) == 0
    assert phone.sync_svc.conflicts() == []


# -- showing the attempt on the record -----------------------------------------------


def test_a_refused_new_record_lists_the_values_it_set(pair):
    laptop, phone, record = pair
    laptop.schema_svc.set_unique_keys("encounter", [["site"]])
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    laptop.record_svc.add("study", "encounter", {"site": "z", "depth": 1.0})
    phone.record_svc.add("study", "encounter", {"site": "z", "depth": 2.0})
    laptop.commit()
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    (refused,) = [c for c in phone.sync_svc.conflicts() if c.kind == "rejected"]

    assert refused.attempted == "create"
    by_name = {c["field_name"]: c for c in refused.changes}
    assert by_name["site"]["before"] is None and by_name["site"]["after"] == "z"
    assert by_name["depth"]["after"] == 2.0
    assert by_name["site"]["field_label"] and by_name["site"]["dtype"] == "string"


def test_an_edit_that_met_a_delete_says_what_it_changed(pair):
    laptop, phone, record = pair
    c = delete_vs_edit(laptop, phone, record)

    assert c.attempted == "update"
    (change,) = [x for x in c.changes if x["field_name"] == "site"]
    assert change["after"] == "edited" and change["current"] == "edited"
    assert change["before"] != "edited"


def test_a_clash_carries_no_attempt_of_its_own(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)

    assert c.attempted is None and c.changes == []


def test_a_clash_can_be_closed_by_having_edited_the_field_by_hand(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)
    phone.record_svc.update(str(record.id), {"site": "by hand", "depth": 1.0})
    phone.commit()

    phone.sync_svc.resolve_conflict(c.id, "edited")

    assert data(phone, record)["site"] == "by hand"
    assert phone.sync_svc.conflicts() == []
    with pytest.raises(ValidationError):
        # Not for a refused change: that is sent again, not closed.
        two_kinds(laptop, phone, record)
        (refused,) = [x for x in phone.sync_svc.conflicts() if x.kind == "rejected"]
        phone.sync_svc.resolve_conflict(refused.id, "edited")


def test_the_conflicts_of_one_record_can_be_listed_open_or_settled(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)
    other = phone.record_svc.add("study", "encounter", {"site": "q", "depth": 1.0})

    assert [x.id for x in phone.sync_svc.conflicts(entity_id=record.id)] == [c.id]
    assert phone.sync_svc.conflicts(entity_id=other.id) == []
    phone.sync_svc.resolve_conflict(c.id, "theirs")
    assert phone.sync_svc.conflicts(entity_id=record.id) == []
    (settled,) = phone.sync_svc.conflicts(None, record.id)
    assert settled.resolution == "theirs" and settled.resolved_at


def test_a_delete_that_met_an_edit_shows_what_the_other_side_changed(pair):
    laptop, phone, record = pair
    laptop.record_svc.update(str(record.id), {"site": "laptop edit", "depth": 1.0})
    phone.record_svc.delete(str(record.id))
    laptop.commit()
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    c = next(x for x in phone.sync_svc.conflicts() if x.kind == "edit_vs_delete")

    assert c.attempted == "delete"
    (change,) = [x for x in c.changes if x["field_name"] == "site"]
    assert change["after"] == "laptop edit" and change["before"] != "laptop edit"
    # Fields they did not touch are not listed.
    assert all(x["field_name"] != "depth" for x in c.changes)


# -- in history ------------------------------------------------------------------------


def test_history_says_what_became_of_a_change_that_did_not_go_in_as_made(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)

    entry = phone.history_svc.get(c.op_id)

    (about,) = entry.sync
    assert about["kind"] == "conflict" and about["status"] == "open"
    assert about["theirs"] == "laptop" and about["yours"] == "phone"
    assert about["field_label"] and about["theirs_actor"] == "laptop"
    # An entry that went in as made says nothing.
    assert all(
        e.sync == [] for e in phone.history_svc.page(limit=50) if e.id != c.op_id
    )


def test_history_follows_the_conflict_to_how_it_was_settled(pair):
    laptop, phone, record = pair
    c = clash(laptop, phone, record)
    phone.sync_svc.resolve_conflict(c.id, "theirs")

    (about,) = phone.history_svc.get(c.op_id).sync

    assert about["status"] == "resolved" and about["resolution"] == "theirs"


def test_a_page_of_history_asks_for_conflicts_once(pair, monkeypatch):
    laptop, phone, record = pair
    clash(laptop, phone, record)
    calls = []
    real = phone.sync_repo.conflicts_of_ops
    monkeypatch.setattr(
        phone.sync_repo, "conflicts_of_ops", lambda ids: calls.append(ids) or real(ids)
    )

    phone.history_svc.page(limit=50)

    assert len(calls) == 1
