"""A record the authority refused (its value no longer allowed there) is waiting
for one fix, not one per attempt, and fixing it is what sends it."""

from __future__ import annotations

import pytest

from .peers import connect, device, snapshots

pytestmark = pytest.mark.usefixtures("strict_schema_lists")


@pytest.fixture()
def calls(project, authority):
    laptop = device(project, authority, "laptop")
    laptop.schema_svc.create("call")
    laptop.schema_svc.add_field("call", "annotation", "string")
    laptop.schema_svc.add_field("call", "note", "string")
    laptop.dataset_svc.create("survey")
    laptop.dataset_svc.update("survey", schemas=["call"])
    laptop.commit()
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    return laptop, phone


def _refusals(ctx):
    return [c for c in ctx.sync_svc.conflicts() if c.kind == "rejected"]


def test_a_refused_record_is_one_item_and_fixing_it_sends_it(calls, authority):
    laptop, phone = calls
    # The laptop adds a record with a free-text annotation...
    made = laptop.record_svc.add(
        "survey", "call", {"annotation": "M (the stepped one)", "note": "a"}
    )
    laptop.commit()
    # ...while the phone narrows the annotation to Y, M or N.
    phone.schema_svc.update_field(
        "call", "annotation", restrictions={"choices": ["Y", "M", "N"]}
    )
    phone.commit()
    phone.sync_svc.sync()

    laptop.sync_svc.sync()
    assert authority.sync_repo.snapshot("record", made.id) is None
    (first,) = _refusals(laptop)
    assert "must be one of" in first.message

    # Sending it again unchanged is refused again, and is still one item.
    laptop.sync_svc.resolve_conflict(first.id, "retry")
    laptop.sync_svc.sync()
    assert len(_refusals(laptop)) == 1

    # Fixing it sends it: the record goes in as it is now, and the item closes.
    laptop.record_svc.update(str(made.id), {"annotation": "M", "note": "b"})  # the fix
    laptop.commit()
    laptop.sync_svc.sync()

    held = authority.record_svc.get(str(made.id)).data
    assert (held["annotation"], held["note"]) == ("M", "b")
    assert _refusals(laptop) == []
    assert laptop.sync_repo.count_pending() == 0
    phone.sync_svc.sync()
    assert phone.record_svc.get(str(made.id)).data["annotation"] == "M"
    assert snapshots(laptop)["record"] == snapshots(authority)["record"]
