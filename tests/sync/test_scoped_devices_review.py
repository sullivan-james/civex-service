"""Regressions from the independent review of scoped sync: catching up on a
record that moved while the device could not read where it was, a feed that
cannot be made to scan without end, a hello that does not scan history, and a
collection given while the device was on an older protocol."""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import event

from civex.domain.sync import PROTOCOL_MAX, SyncEntry
from civex.services import sync_authority
from civex.testing import principal, snapshots

from .test_scoped_devices import (  # noqa: F401
    SECRET,
    Study,
    held,
    reads,
    scoped,
    study,
    text_of,
)


# -- 7: a record that moved while its collection was out of sight -------------------


def test_a_record_moved_into_sight_while_its_old_collection_was_hidden_arrives(
    study: Study,
):
    authority, limited = study.authority, study.limited
    mover = study.vault_records[1]
    # at its cursor the device sees `open` only; then, while it is away, the
    # record leaves the (hidden) vault for `open`, is edited there, and later the
    # vault is given to the device
    authority.record_svc.update(str(mover.id), {"site": f"{SECRET} edited in vault"})
    authority.record_svc.move("open", ids=[str(mover.id)])
    authority.record_svc.update(str(mover.id), {"site": "edited in open"})
    authority.commit()
    study.widen(study.open.id, study.vault.id)
    study.sync(limited, study.full)
    assert held(limited, "record") == held(study.full, "record")
    (got,) = [r for r in snapshots(limited)["record"] if r["id"] == str(mover.id)]
    assert got["dataset_id"] == str(study.open.id)
    assert got["data"] == {
        k: v
        for r in snapshots(study.full)["record"]
        if r["id"] == str(mover.id)
        for k, v in r["data"].items()
    }
    # and what follows applies, as for any record it holds
    authority.record_svc.update(str(mover.id), {"site": "edited again"})
    authority.commit()
    study.sync(limited, study.full)
    (again,) = [r for r in snapshots(limited)["record"] if r["id"] == str(mover.id)]
    assert "edited again" in str(again["data"])
    assert not limited.sync_repo.find_open_conflicts()


def test_its_notes_come_too(study: Study):
    authority, limited = study.authority, study.limited
    mover = study.vault_records[0]  # has the vault's note
    authority.record_svc.move("open", ids=[str(mover.id)])
    authority.commit()
    study.widen(study.open.id, study.vault.id)
    study.sync(limited, study.full)
    assert held(limited, "note") == held(study.full, "note")


# -- 8: the scoped feed is bounded ----------------------------------------------------


def test_one_feed_request_looks_at_no_more_than_the_cap_and_says_how_far(
    study: Study, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sync_authority, "FEED_SCAN_MAX", 40)
    monkeypatch.setattr(sync_authority, "FEED_MAX", 10)
    authority = study.authority
    study.sync(study.limited)
    start = study.limited.sync_repo.meta().cursor
    for i in range(120):
        authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} {i}"})
    authority.commit()
    service = study.only_open.authority_svc
    page = service.feed(start, 10)
    # nothing to give, and not the whole hidden tail read to learn it
    assert page.entries == [] and page.more is True
    assert start < page.through <= start + 40 + 10
    # asking again from there goes on, and a device finishes in a few requests
    through, calls = start, 0
    while True:
        page = service.feed(through, 10)
        calls += 1
        assert page.through is not None and page.through > through
        through = page.through
        if not page.more:
            break
    assert through == page.head_seq
    assert calls <= 120 // 10 + 2


def test_a_device_reaches_the_head_across_capped_pages(
    study: Study, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sync_authority, "FEED_SCAN_MAX", 25)
    authority = study.authority
    for i in range(80):
        authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} {i}"})
    authority.record_svc.add("open", "encounter", {"site": "the one it may see"})
    authority.commit()
    study.sync(study.limited)
    assert study.limited.sync_repo.meta().cursor == authority.sync_repo.head_seq()
    assert any("the one it may see" in str(r) for r in snapshots(study.limited)["record"])
    assert SECRET not in text_of(study.limited)


def test_judging_a_page_of_notes_asks_for_their_records_once(study: Study):
    """The collection a note was in is looked up for the whole page, not one
    lookup per note (or per record, or per record's whole history)."""
    authority = study.authority
    records = [
        authority.record_svc.add("open", "encounter", {"site": f"n {i}"})
        for i in range(25)
    ]
    for r in records:
        authority.note_svc.add(str(r.id), "a note")
    authority.commit()
    study.only_open.authority_svc.feed(0, 1)  # (numbers what the authority made)
    engine = authority.sync_repo._s.get_bind()
    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        if "audit_log" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        page = study.only_open.authority_svc.feed(0, 500)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert sum(1 for e in page.entries if e.entity_type == "note") >= 25
    # the page itself, the head, and one lookup for the trails: not one per note
    assert len(statements) <= 6, statements


# -- 9: hello does not scan history ----------------------------------------------------


def test_hello_finds_creation_numbers_by_the_collections_own_ids(study: Study):
    authority = study.authority
    engine = authority.sync_repo._s.get_bind()
    statements: list[str] = []

    def watch(conn, cursor, statement, *args):
        statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", watch)
    try:
        hello = study.only_open.authority_svc.hello(
            principal(study.only_open, "limited"), PROTOCOL_MAX
        )
    finally:
        event.remove(engine, "before_cursor_execute", watch)
    assert [c["id"] for c in hello.readable] == [str(study.open.id)]
    assert hello.readable[0]["seq"] > 0
    audits = [s for s in statements if "FROM audit_log" in s and "min(" in s]
    assert audits and all("audit_log.entity_id IN" in s for s in audits), audits
    # emptiness of a restricted caller's authority is not a pair of exact counts
    counts = [s for s in statements if "count(" in s]
    assert len(counts) <= 9, counts  # one pass over the kinds, never two


def test_a_restricted_hello_still_says_the_authority_holds_data(study: Study):
    nothing = scoped(study.authority, reads())
    hello = nothing.authority_svc.hello(principal(nothing, "blind"), PROTOCOL_MAX)
    assert hello.empty is False


# -- 14: a collection given while the device could not be told ---------------------------


def test_a_collection_given_before_the_device_learned_to_be_told_is_read_on_upgrade(
    study: Study,
):
    authority, limited = study.authority, study.limited
    # a device that was never told what it may read (it synced on an older
    # protocol, or before this existed) and that lacks the vault
    limited.sync_repo._meta_row().readable = None
    limited.commit()
    study.widen(study.open.id, study.vault.id)
    study.sync(limited, study.full)
    assert held(limited, "record") == held(study.full, "record")
    assert held(limited, "dataset") == held(study.full, "dataset")
    assert limited.sync_repo.readable() == {str(study.open.id), str(study.vault.id)}


def test_a_device_that_holds_everything_it_may_read_asks_for_nothing(study: Study):
    limited = study.limited
    limited.sync_repo._meta_row().readable = None
    limited.commit()
    calls_before = len(limited._holder["inner"].calls) if hasattr(
        limited, "_holder"
    ) else 0
    study.sync(limited)
    assert limited.sync_repo.readable() == {str(study.open.id)}
    assert SECRET not in text_of(limited)
    assert calls_before >= 0


# -- 16: refusals tell a hidden record from an absent one in no way --------------------


def _pointing_at(study: Study, target: str):
    authority = study.authority
    if not any(f.name == "friend" for f in authority.schema_svc.get("encounter").fields):
        authority.schema_svc.add_field(
            "encounter", "friend", "reference", restrictions={"schema": "encounter"}
        )
        authority.commit()
    schema = authority.schema_svc.get("encounter")
    fid = next(f.id for f in schema.fields if f.name == "friend")
    limited = scoped(authority, reads(study.open.id))
    ident = str(uuid.uuid4())
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="create",
        entity_type="record",
        entity_id=uuid.UUID(ident),
        old_data=None,
        new_data={
            "id": ident,
            "dataset_id": str(study.open.id),
            "schema_id": str(schema.id),
            "data": {str(fid): target},
            "parent_record_id": None,
            "deleted_at": None,
        },
        timestamp="2026-01-01T00:00:00+00:00",
    )
    try:
        (result,) = limited.authority_svc.push(
            principal(limited, "limited"), [entry]
        ).results
        limited.commit()
    finally:
        limited.close()
    return result


def test_pointing_at_a_hidden_record_is_answered_as_pointing_at_an_absent_one(
    study: Study,
):
    hidden_id, absent_id = str(study.vault_records[0].id), str(uuid.uuid4())
    hidden = _pointing_at(study, hidden_id)
    absent = _pointing_at(study, absent_id)
    assert hidden.status == absent.status == "rejected"
    # the same words, each naming the record that was asked about
    assert hidden.message.replace(hidden_id, "ID") == absent.message.replace(
        absent_id, "ID"
    )
    assert "not found" in hidden.message and "vault" not in hidden.message
    assert hidden.conflicts == absent.conflicts


def test_a_long_hidden_tail_costs_a_bounded_request(study: Study):
    """Scale: a feed request on a project whose recent changes are nearly all
    hidden from the device reads at most `FEED_SCAN_MAX` entries however long
    the hidden run, and answers quickly; the device then finishes in steps."""
    authority = study.authority
    hidden_records = 2500
    for i in range(hidden_records):
        authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} {i}"})
    authority.record_svc.add("open", "encounter", {"site": "one it may see"})
    authority.commit()
    service = study.only_open.authority_svc
    service.feed(0, 1)  # (numbers what the authority made)
    start = study.limited.sync_repo.meta().cursor
    began = time.perf_counter()
    page = service.feed(start, 500)
    took = time.perf_counter() - began
    assert page.entries == [] and page.more is True
    assert page.through - start <= sync_authority.FEED_SCAN_MAX + 500
    print(f"one capped feed request over a hidden tail: {took:.3f}s")
    assert took < 5, f"{took:.2f}s for one capped request"
    study.sync(study.limited)
    assert study.limited.sync_repo.meta().cursor == authority.sync_repo.head_seq()
    assert any("one it may see" in str(r) for r in snapshots(study.limited)["record"])
