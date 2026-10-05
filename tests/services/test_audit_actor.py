"""Every history entry records who made it, as far as this machine can say."""

from __future__ import annotations

import getpass

import pytest

from civex import identity
from civex.context import AppContext


def test_local_actor_is_the_os_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getuser", lambda: "  alice ")
    assert identity.local_actor() == "alice"


def test_local_actor_is_none_when_the_os_has_no_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> str:
        raise KeyError("getpwuid(): uid not found")

    monkeypatch.setattr(getpass, "getuser", boom)
    assert identity.local_actor() is None


def test_local_actor_fits_the_column(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getuser", lambda: "x" * 300)
    assert len(identity.local_actor() or "") == 100


def test_new_entries_carry_the_actor_and_it_is_served(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    make_schema("thing", fields=[("title", "string")])
    make_collection("study")
    record = make_record("study", "thing", {"title": "a"})

    entries = ctx.history_svc.page(entity_id=record.id, limit=10)
    assert entries
    assert {e.actor for e in entries} == {identity.local_actor()}


def test_a_permanent_delete_names_who_did_it(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    make_schema("thing", fields=[("title", "string")])
    make_collection("study")
    record = make_record("study", "thing", {"title": "a"})
    ctx.record_svc.delete(str(record.id))
    ctx.commit()
    ctx.record_svc.purge(str(record.id))
    ctx.commit()

    tombstone = [
        e
        for e in ctx.history_svc.page(entity_id=record.id, limit=10)
        if e.action == "purge"
    ]
    assert tombstone and tombstone[0].actor == identity.local_actor()


def test_an_event_says_who_made_it_including_a_bulk_one(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("rate", "integer")], parent="encounter")
    make_collection("c")
    enc = make_record("c", "encounter", {"site": "x"})
    make_record("c", "recording", {"rate": 1}, parent_record_id=str(enc.id))
    ctx.record_svc.delete(str(enc.id))  # a bulk delete: one event, two records
    ctx.commit()

    events, _ = ctx.history_svc.events(
        where={"and": [{"field": "change", "op": "eq", "value": "delete"}]}, limit=5
    )
    assert events[0].batch is not None
    assert events[0].actor == identity.local_actor()
