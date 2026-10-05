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
