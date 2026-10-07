"""A record that sits under a deleted one here is refused by the server. Its
review offers to bring back what it sits under and send it again, which puts
it in place on every copy."""

from __future__ import annotations

import pytest
from sqlalchemy import update

from civex.db.models import Record

from .peers import connect, device

pytestmark = pytest.mark.usefixtures("strict_schema_lists")


def test_a_refused_orphan_comes_back_with_what_it_sits_under(project, authority):
    laptop = device(project, authority, "laptop")
    laptop.schema_svc.create("recording")
    laptop.schema_svc.add_field("recording", "label", "string")
    laptop.schema_svc.create("selection", parent="recording")
    laptop.schema_svc.add_field("selection", "n", "integer")
    laptop.dataset_svc.create("survey")
    laptop.dataset_svc.update("survey", schemas=["recording", "selection"])
    rec = laptop.record_svc.add("survey", "recording", {"label": "R"})
    sels = [
        laptop.record_svc.add(
            "survey", "selection", {"n": i}, parent_record_id=str(rec.id)
        )
        for i in range(2)
    ]
    laptop.commit()
    connect(laptop)
    laptop.record_svc.delete(str(rec.id))
    laptop.commit()
    laptop.sync_svc.sync()

    # How the orphan came about: one selection back by itself, no history.
    sel = sels[0]
    laptop._session.execute(
        update(Record).where(Record.id == sel.id).values(deleted_at=None)
    )
    laptop.record_svc.update(str(sel.id), {"n": 9})
    laptop.commit()
    laptop.sync_svc.sync()

    (refused,) = [c for c in laptop.sync_svc.conflicts() if c.kind == "rejected"]
    assert [u["id"] for u in refused.sits_under] == [str(rec.id)]
    assert "restore_above" in refused.takes

    laptop.sync_svc.resolve_conflict(refused.id, "restore_above")
    laptop.sync_svc.sync()

    assert laptop.sync_svc.conflicts() == []
    assert authority.record_svc.get(str(rec.id)).deleted_at is None
    assert authority.record_svc.get(str(sel.id)).data["n"] == 9
    # Its sibling stays deleted everywhere.
    assert authority._session.get(Record, sels[1].id).deleted_at is not None
