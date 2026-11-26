"""A device catching up on a feed applies runs of like record changes as a set;
every row it keeps, and everything it holds or refuses, is what applying the
changes one at a time gives (`SyncService._bulk_pull` off), on SQLite and on
PostgreSQL (CIVEX_TEST_POSTGRES_URL)."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from civex.services import sync_service
from civex.services.sync_service import SyncService
from civex.testing.peers import build_study, connect, device

_SERVER = os.environ.get("CIVEX_TEST_POSTGRES_URL")

TABLES = {
    "records": "SELECT id, dataset_id, schema_id, parent_record_id, data, created_at, "
    "updated_at, deleted_at FROM records ORDER BY id",
    "audit_log": "SELECT id, action, entity_type, entity_id, old_data, new_data, delta, "
    "format, op_id, batch_id, timestamp, actor, device, device_id, hlc, hub_seq, "
    "sync_state, apply_state FROM audit_log WHERE hub_seq IS NOT NULL "
    "ORDER BY hub_seq, id",
    "pending_audit": "SELECT action, entity_type, entity_id, sync_state, apply_state "
    "FROM audit_log WHERE hub_seq IS NULL ORDER BY entity_id, action",
    "audit_batches": "SELECT id, kind, label, ref, created_at FROM audit_batches "
    "ORDER BY id",
    "sync_conflicts": "SELECT kind, entity_type, entity_id, field, yours, theirs, "
    "status, message FROM sync_conflicts ORDER BY entity_id, kind, field",
    "file_references": "SELECT sha256, record_id, volume FROM file_references "
    "ORDER BY record_id, sha256",
    "record_references": "SELECT record_id, field_id, target_id FROM record_references "
    "ORDER BY record_id, field_id",
    "sync_meta": "SELECT head_seq, cursor, feed_floor, placed_from FROM sync_meta",
}


def _utc(value: str) -> str:
    """A stored time as UTC, whatever the database's own zone shows."""
    if value == "None":
        return value
    at = datetime.fromisoformat(value)
    return at.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def dump(ctx) -> dict[str, list]:
    ctx.commit()
    return {
        name: [tuple(map(str, r)) for r in ctx._session.execute(text(sql)).all()]
        for name, sql in TABLES.items()
    }


def service(ctx) -> SyncService:
    inner = ctx.sync_svc
    return object.__getattribute__(inner, "_svc") if hasattr(inner, "_svc") else inner


@pytest.fixture(params=["sqlite", "postgres"])
def backend(request, tmp_path):
    if request.param == "sqlite":
        yield None
        return
    if not _SERVER:
        pytest.skip("CIVEX_TEST_POSTGRES_URL not set")
    admin = create_engine(_SERVER, isolation_level="AUTOCOMMIT")
    names = []

    def make() -> str:
        name = f"civex_{uuid.uuid4().hex[:12]}"
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        names.append(name)
        return _SERVER.rsplit("/", 1)[0] + f"/{name}"

    yield make
    request.getfixturevalue("project").close()  # (before its databases go)
    with admin.connect() as conn:
        for name in names:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture()
def spy(monkeypatch):
    """How many changes each service applied as a run."""
    taken: dict[int, int] = {}
    real = SyncService._run

    def run(self, *args, **kwargs):
        out = real(self, *args, **kwargs)
        taken[id(self)] = taken.get(id(self), 0) + len(out[0])
        return out

    monkeypatch.setattr(SyncService, "_run", run)
    return taken


class Trio:
    """A laptop that makes the changes, and two phones that catch up on them:
    `old` one change at a time, `new` with runs. Both are joined (and have the
    study) before the laptop acts."""

    def __init__(self, project, authority, backend, n: int = 30) -> None:
        make = (lambda name: project(name, db_url=backend())) if backend else project
        self.authority = authority
        self.laptop = device(project, authority, "laptop")
        build_study(self.laptop)
        connect(self.laptop)
        self.old = device(make, authority, "old")
        connect(self.old)
        self.new = device(make, authority, "new")
        connect(self.new)
        service(self.old)._bulk_pull = False
        self.ids: list[str] = []
        self.add(n)

    def add(self, n: int) -> list[str]:
        made = [
            str(
                self.laptop.record_svc.add(
                    "study",
                    "encounter",
                    {"site": f"s{len(self.ids) + i}", "depth": 1.0},
                ).id
            )
            for i in range(n)
        ]
        self.laptop.commit()
        self.ids += made
        return made

    def send(self) -> None:
        self.laptop.commit()
        self.laptop.sync_svc.sync()
        self.authority.sync_repo.sequence_local_entries()
        self.authority.commit()

    def catch_up(self) -> None:
        for phone in (self.old, self.new):
            phone.sync_svc._pull(phone.sync_svc._transport())
            phone.commit()

    def same(self) -> None:
        a, b = dump(self.old), dump(self.new)
        for name in TABLES:
            assert a[name] == b[name], name


def test_creates_edits_deletes_and_restores_end_as_one_at_a_time_does(
    project, authority, backend, spy
):
    t = Trio(project, authority, backend)
    t.send()
    t.laptop.record_svc.bulk_edit({"depth": 9.0}, ids=t.ids[:20])
    t.laptop.commit()
    t.send()
    t.laptop.record_svc.delete_many(t.ids[5:25])
    t.laptop.commit()
    t.send()
    t.laptop.record_svc.restore_set(t.ids[10:15])
    t.laptop.commit()
    t.send()
    t.catch_up()
    t.same()
    assert spy[id(service(t.new))] > 40
    assert id(service(t.old)) not in spy or spy[id(service(t.old))] == 0
    live = {r[0] for r in dump(t.new)["records"] if r[-1] == "None"}
    assert len(live) == 31 - 15  # (the study's own record too)


def test_a_page_with_a_delete_and_a_restore_of_the_same_record(
    project, authority, backend, spy
):
    t = Trio(project, authority, backend, n=12)
    t.send()
    t.laptop.record_svc.delete_many(t.ids)
    t.laptop.commit()
    t.send()
    t.laptop.record_svc.restore_set(t.ids[:6])
    t.laptop.commit()
    t.send()
    t.laptop.record_svc.delete_many(t.ids[:3])
    t.laptop.commit()
    t.send()
    t.catch_up()
    t.same()
    assert spy[id(service(t.new))] > 12


def test_the_same_feed_in_small_pages(project, authority, backend, spy, monkeypatch):
    t = Trio(project, authority, backend)
    t.send()
    t.laptop.record_svc.delete_many(t.ids[:17])
    t.laptop.commit()
    t.send()
    t.laptop.record_svc.restore_set(t.ids[:9])
    t.laptop.commit()
    t.send()
    monkeypatch.setattr(sync_service, "FEED_PAGE", 7)
    t.catch_up()
    t.same()


def test_a_change_of_ours_not_sent_yet_holds_what_the_server_deleted(
    project, authority, backend, spy
):
    t = Trio(project, authority, backend)
    t.send()
    t.catch_up()
    t.laptop.record_svc.delete_many(t.ids[:20])
    t.laptop.commit()
    t.send()
    for phone in (t.old, t.new):
        phone.record_svc.update(t.ids[3], {"site": "mine", "depth": 5.0})
        phone.record_svc.update(t.ids[12], {"site": "mine", "depth": 5.0})
        phone.commit()
    t.catch_up()
    # (the phones' own entries have ids of their own: compared as the rows they
    # leave, then what a full sync settles)
    a, b = dump(t.old), dump(t.new)
    for d in (a, b):  # (the phones made their own edits at times of their own)
        d["records"] = [r[:6] + r[7:] for r in d["records"]]
    for name in TABLES:
        assert a[name] == b[name], name
    held = [r for r in a["audit_log"] if r[-1] == "held"]
    assert len(held) == 2
    assert spy[id(service(t.new))] >= 15
    for phone in (t.old, t.new):
        phone.sync_svc.sync()
        phone.commit()
    a, b = dump(t.old), dump(t.new)
    # (what each phone sent has ids and times of its own: the records are compared)
    assert [r[:6] + r[7:] for r in a["records"]] == [
        r[:6] + r[7:] for r in b["records"]
    ]


def test_parents_and_children(project, authority, backend, spy):
    t = Trio(project, authority, backend, n=0)
    t.laptop.schema_svc.create("recording", parent="encounter")
    t.laptop.schema_svc.add_field("recording", "site", "string")
    t.laptop.schema_svc.add_field("recording", "depth", "float")
    t.laptop.commit()
    parents = t.add(6)
    t.send()
    t.catch_up()

    def children(n: int, tag: str) -> list[str]:
        made = [
            str(
                t.laptop.record_svc.add(
                    "study",
                    "recording",
                    {"site": f"{tag}{i}", "depth": 2.0},
                    parent_record_id=parents[i % 6],
                ).id
            )
            for i in range(n)
        ]
        t.laptop.commit()
        return made

    kids = children(24, "k")
    t.send()
    t.catch_up()
    t.same()
    parent_ids = {r[3] for r in dump(t.new)["records"]} - {"None"}
    assert len(parent_ids) == 6  # (they really sit under their parents)
    # An unsent edit of ours to a child holds what the server puts beside it.
    for phone in (t.old, t.new):
        phone.record_svc.update(kids[0], {"site": "mine", "depth": 3.0})
        phone.commit()
    t.laptop.record_svc.bulk_edit({"depth": 4.0}, ids=parents)
    more = children(12, "m")
    t.laptop.record_svc.delete_many(parents[3:])  # takes the children with them
    t.laptop.commit()
    t.send()
    t.laptop.record_svc.restore_set(kids[:3] + more[:2])
    t.laptop.commit()
    t.send()
    t.catch_up()
    a, b = dump(t.old), dump(t.new)
    for d in (a, b):
        d["records"] = [r[:6] + r[7:] for r in d["records"]]
    for name in TABLES:
        assert a[name] == b[name], name
    assert any(r[-1] == "held" for r in a["audit_log"])
    assert spy[id(service(t.new))] > 20


def test_edits_that_cite_files_and_records(project, authority, backend, spy):
    t = Trio(project, authority, backend, n=8)
    t.laptop.schema_svc.add_field("encounter", "scan", "file")
    t.laptop.commit()
    t.send()
    for i, rid in enumerate(t.ids):
        ref = t.laptop.file_svc.store_bytes(f"scan {i}".encode(), "scan.bin")
        t.laptop.record_svc.update(
            rid, {"site": f"s{i}", "depth": 1.0, "scan": ref.to_dict()}
        )
    t.laptop.commit()
    t.send()
    t.catch_up()
    t.same()
    assert len(dump(t.new)["file_references"]) == 8


def test_two_devices_pulling_each_others_bulk_actions_converge(
    project, authority, backend, spy
):
    t = Trio(project, authority, backend)
    t.send()
    t.catch_up()
    t.laptop.record_svc.delete_many(t.ids[:12])
    t.laptop.commit()
    for phone in (t.old, t.new):
        phone.record_svc.bulk_edit({"depth": 7.0}, ids=t.ids[8:24])
        phone.commit()
    for _ in range(4):
        for ctx in (t.laptop, t.old, t.new):
            ctx.sync_svc.sync()
            ctx.commit()
            t.authority.sync_repo.sequence_local_entries()
            t.authority.commit()

    def state(ctx):
        return [
            (
                r[0].replace("-", ""),
                json.dumps(
                    ast.literal_eval(r[4])
                    if r[4].startswith("{'")
                    else json.loads(r[4]),
                    sort_keys=True,
                ),
                _utc(r[7]),
            )
            for r in dump(ctx)["records"]
        ]

    assert state(t.old) == state(t.new) == state(t.laptop) == state(t.authority)


def test_a_run_the_database_refuses_is_done_one_at_a_time(
    project, authority, backend, spy, monkeypatch
):
    from civex.domain.exceptions import ValidationError
    from civex.repositories.local.sync_repo import LocalSyncRepository

    real = LocalSyncRepository.soft_delete_records

    def refuse(self, stamps):
        real(self, stamps)  # (written, then refused: the savepoint undoes it)
        raise ValidationError("refused")

    t = Trio(project, authority, backend, n=12)
    t.send()
    t.laptop.record_svc.delete_many(t.ids)
    t.laptop.commit()
    t.send()
    monkeypatch.setattr(LocalSyncRepository, "soft_delete_records", refuse)
    t.catch_up()
    t.same()
    assert spy[id(service(t.new))] <= 12  # (the creates; no delete run stood)


def test_a_run_the_database_refuses_leaves_the_records_it_loaded_as_they_are(
    project, authority, backend, spy, monkeypatch
):
    """A refused run is undone, and so is what the delete told the records the
    session already holds (it must not keep saying they are deleted)."""
    from civex.domain.exceptions import ValidationError
    from civex.repositories.local.sync_repo import LocalSyncRepository

    real = LocalSyncRepository.soft_delete_records

    def refuse(self, items):
        real(self, items)
        raise ValidationError("refused")

    t = Trio(project, authority, backend, n=12)
    t.send()
    t.catch_up()
    t.laptop.record_svc.delete_many(t.ids)
    t.laptop.commit()
    t.send()
    from civex.db.models import Record

    held = [  # (the session holds each, live, for as long as this list does)
        phone._session.get(Record, uuid.UUID(rid))
        for phone in (t.old, t.new)
        for rid in t.ids
    ]
    assert all(r is not None and r.deleted_at is None for r in held)
    monkeypatch.setattr(LocalSyncRepository, "soft_delete_records", refuse)
    t.catch_up()
    t.same()
    assert not [r for r in dump(t.new)["records"] if r[0] in t.ids and r[-1] == "None"]


def test_an_action_of_ten_with_its_last_member_changed_here_is_held_whole(
    project, authority, backend, spy
):
    t = Trio(project, authority, backend, n=0)
    t.laptop.schema_svc.create("recording", parent="encounter")
    t.laptop.schema_svc.add_field("recording", "site", "string")
    t.laptop.schema_svc.add_field("recording", "depth", "float")
    t.laptop.commit()
    parent, other = t.add(2)
    t.send()
    t.catch_up()
    kids = [
        str(
            t.laptop.record_svc.add(
                "study",
                "recording",
                {"site": f"k{i}", "depth": 2.0},
                parent_record_id=parent,
            ).id
        )
        for i in range(9)
    ]
    t.laptop.commit()
    t.send()
    t.catch_up()
    for phone in (t.old, t.new):
        phone.record_svc.update(kids[-1], {"site": "mine", "depth": 3.0})
        phone.commit()
    t.laptop.record_svc.delete_many([parent, other])  # a tree each: 10 and 1
    t.laptop.commit()
    t.send()
    action = str(uuid.uuid4())
    mine = {parent.replace("-", ""), *(k.replace("-", "") for k in kids)}
    for phone in (t.old, t.new):
        transport = phone.sync_svc._transport()
        feed = transport.feed

        def with_op(cursor, limit, feed=feed):
            page = feed(cursor, limit)
            for e in page.entries:  # (the authority's feed carries no `op`)
                if e.action == "delete" and e.entity_id.hex in mine:
                    e.op = action
            return page

        transport.feed = with_op
        phone.sync_svc._pull(transport)
        phone.commit()
    a, b = dump(t.old), dump(t.new)
    for d in (a, b):
        d["records"] = [r[:6] + r[7:] for r in d["records"]]  # (our edit's time)
    for name in TABLES:
        assert a[name] == b[name], name
    held = [r for r in dump(t.new)["audit_log"] if r[-1] == "held"]
    assert len(held) == 10  # (the other tree went in)
    live = {r[0] for r in dump(t.new)["records"] if r[-1] == "None"}
    assert parent.replace("-", "") in live and other.replace("-", "") not in live


def test_a_superseded_change_inside_a_run_is_kept_not_applied(
    project, authority, backend, spy
):
    t = Trio(project, authority, backend, n=12)
    t.send()
    t.catch_up()
    t.laptop.record_svc.delete_many(t.ids)
    t.laptop.commit()
    t.send()
    odd = t.ids[5]
    for phone in (t.old, t.new):
        transport = phone.sync_svc._transport()
        feed = transport.feed

        def marked(cursor, limit, feed=feed):
            page = feed(cursor, limit)
            for e in page.entries:
                if str(e.entity_id) == odd and e.action == "delete":
                    e.superseded = True  # (another device's, settled otherwise)
            return page

        transport.feed = marked
        phone.sync_svc._pull(transport)
        phone.commit()
    t.same()
    assert (
        spy[id(service(t.new))] == 12 + 11
    )  # (the creates; 5, then 6 after the odd one)
    live = {r[0] for r in dump(t.new)["records"] if r[-1] == "None"}
    assert odd.replace("-", "") in live and len(live) == 2


def test_a_page_of_moves_is_not_read_again_for_each_move(
    project, authority, backend, spy, monkeypatch
):
    from civex.repositories.local.sync_repo import LocalSyncRepository

    n = 40
    t = Trio(project, authority, backend, n=n)
    t.laptop.dataset_svc.create("other")
    t.laptop.commit()
    t.send()
    t.catch_up()
    t.laptop.record_svc.move("other", ids=t.ids)
    t.laptop.commit()
    t.send()
    asked: list[int] = []
    real = LocalSyncRepository.record_rows

    def counted(self, ids):
        asked.append(len(ids))
        return real(self, ids)

    monkeypatch.setattr(LocalSyncRepository, "record_rows", counted)
    t.catch_up()
    t.same()
    # (each move is looked at a few times at most, not once per move after it)
    assert sum(asked) <= 6 * n, sum(asked)
