"""A pushed run of record deletes (or restores) is written in bulk; what each
entry is answered, and every row the authority keeps (history with its batch,
the answers, the records, the feed's numbers), is what settling the entries one
at a time gives (`SyncAuthorityService._bulk` off). Run on SQLite, and on
PostgreSQL when CIVEX_TEST_POSTGRES_URL is set."""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from civex.context import build_context
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.domain.sync import SyncEntry

from .test_bulk_push import rows as base_rows
from .test_bulk_push import send

_SERVER = os.environ.get("CIVEX_TEST_POSTGRES_URL")


@pytest.fixture(params=["sqlite", "postgres"])
def pair(request, project):
    """Two authorities on the same kind of database: one writing in bulk, one
    settling each change on its own."""
    if request.param == "sqlite":
        fast, slow = project("authority-bulk"), project("authority-single")
        slow.authority_svc._bulk = False
        yield fast, slow
        return
    if not _SERVER:
        pytest.skip("CIVEX_TEST_POSTGRES_URL not set")
    admin = create_engine(_SERVER, isolation_level="AUTOCOMMIT")
    names = [f"civex_{uuid.uuid4().hex[:12]}" for _ in range(2)]
    ctxs = []
    for name in names:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        ctxs.append(project(name, db_url=_SERVER.rsplit("/", 1)[0] + f"/{name}"))
    ctxs[1].authority_svc._bulk = False
    yield ctxs[0], ctxs[1]
    project.close()
    for name in names:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def rows(ctx) -> dict[str, list]:
    out = base_rows(ctx)
    for name, sql in {
        "audit_batches": "SELECT id, kind, label, ref FROM audit_batches ORDER BY id",
        "audit_ext": "SELECT id, batch_id, hlc, actor, device, device_id, old_data, "
        "new_data FROM audit_log ORDER BY hub_seq, id",
    }.items():
        out[name] = [tuple(map(str, r)) for r in ctx._session.execute(text(sql)).all()]
    # (what the authority writes itself has an id, a stamp and times of its own)
    out["audit_ext"] = [("sync",) if r[3] == "sync" else r for r in out["audit_ext"]]
    return out


class Flow:
    """A laptop's structure and records; what it does is sent as entries."""

    def __init__(self, project) -> None:
        self.laptop = laptop = project("laptop")
        laptop.schema_svc.create("species")
        laptop.schema_svc.add_field("species", "latin", "string")
        laptop.schema_svc.create("encounter")
        laptop.schema_svc.add_field("encounter", "site", "string")
        laptop.schema_svc.add_field("encounter", "depth", "float")
        laptop.schema_svc.add_field(
            "encounter", "seen", "reference", restrictions={"schema": "species"}
        )
        laptop.schema_svc.create("recording", parent="encounter")
        laptop.schema_svc.add_field("recording", "label", "string")
        laptop.schema_svc.add_field("recording", "must", "string", required=True)
        laptop.schema_svc.set_unique_keys("recording", [["label"]])
        for name in ("mine", "theirs", "secret"):
            laptop.dataset_svc.create(name)
        laptop.dataset_svc.create("taxa", scope="global")
        laptop.commit()
        self.structure = self.take()

    def take(self) -> list[SyncEntry]:
        entries = self.laptop.sync_repo.pending_entries(10_000)
        self.laptop.sync_repo.mark_all_synced()
        self.laptop.commit()
        return entries

    def make(self, dataset, schema, values, parent=None) -> uuid.UUID:
        made = self.laptop.record_svc.add(
            dataset, schema, values, parent_record_id=parent
        )
        self.laptop.commit()
        return made.id

    def many(self, n, dataset="mine") -> list[uuid.UUID]:
        return [
            self.make(dataset, "encounter", {"site": f"s{i}", "depth": float(i)})
            for i in range(n)
        ]

    def deleted(self, ids) -> list[SyncEntry]:
        self.laptop.record_svc.delete_many([str(i) for i in ids], force=True)
        self.laptop.commit()
        return self.take()

    def restored(self, ids) -> list[SyncEntry]:
        self.laptop.record_svc.restore_set([str(i) for i in ids])
        self.laptop.commit()
        return self.take()


def edit_entry(create: SyncEntry, **values) -> SyncEntry:
    """Another device's edit of a record, as an entry: both authorities take
    the very same one (so what they keep of it is equal)."""
    key = {k: v for k, v in create.new_data["data"].items()}
    new = {**create.new_data, "updated_at": "2030-01-01T00:00:00+00:00"}
    new["data"] = {
        k: ("edited" if isinstance(v, str) else v + 1.0) for k, v in key.items()
    }
    return dataclasses.replace(
        create,
        id=uuid.uuid4(),
        action="update",
        old_data=create.new_data,
        new_data=new,
        timestamp="2030-01-01T00:00:00+00:00",
        hlc=None,
    )


def with_label(create: SyncEntry, label: str) -> SyncEntry:
    """Another record, new in every id, with this label."""
    fresh = uuid.uuid4()
    data = {k: (label if v == "x" else v) for k, v in create.new_data["data"].items()}
    return dataclasses.replace(
        create,
        id=uuid.uuid4(),
        entity_id=fresh,
        new_data={**create.new_data, "id": str(fresh), "data": data},
    )


def both(pair, batches, calls=None):
    """Send each batch to both authorities; answers and rows must agree."""
    out = []
    for batch in batches:
        answers = [send(a, batch) for a in pair]
        assert answers[0] == answers[1]
        assert rows(pair[0]) == rows(pair[1])
        out.append(answers[0][0])
    return out


@pytest.fixture()
def spy(pair, monkeypatch):
    calls = {"delete": [], "restore": []}
    fast = pair[0]
    real_d, real_r = fast.sync_repo.soft_delete_records, fast.sync_repo.restore_records

    def d(items):
        calls["delete"].append(len(items))
        return real_d(items)

    def r(ids):
        calls["restore"].append(len(ids))
        return real_r(ids)

    monkeypatch.setattr(fast.sync_repo, "soft_delete_records", d)
    monkeypatch.setattr(fast.sync_repo, "restore_records", r)
    return calls


def test_a_bulk_delete_then_restore_is_kept_as_one_at_a_time(project, pair, spy):
    f = Flow(project)
    ids = f.many(12)
    creates = f.take()
    for a in pair:
        send(a, f.structure + creates)
    gone = f.deleted(ids)
    assert all(e.batch is not None and e.op for e in gone)  # as a real one is
    back = f.restored(ids)
    answers = both(pair, [gone, back])
    assert [r[1] for r in answers[0]] == ["applied"] * 12
    assert [r[1] for r in answers[1]] == ["applied"] * 12
    assert spy["delete"] == [12] and spy["restore"] == [12]
    assert rows(pair[0])["audit_batches"]


def test_a_batch_sent_again_is_answered_as_before(project, pair, spy):
    f = Flow(project)
    ids = f.many(5)
    first = f.structure + f.take()
    for a in pair:
        send(a, first)
    gone = f.deleted(ids)
    answers = both(pair, [gone, gone])
    assert all(r[5] for r in answers[1])  # replayed
    assert spy["delete"] == [5]  # (the second time nothing was written)


def test_mixed_entries_are_answered_in_order(project, pair, spy):
    f = Flow(project)
    ids = f.many(10)
    first = f.structure + f.take()
    for a in pair:
        send(a, first)
    gone = f.deleted(ids[:4])
    back = f.restored(ids[:2])
    f.laptop.record_svc.update(str(ids[6]), {"site": "edited", "depth": 1.0})
    f.laptop.commit()
    edit = f.take()
    new = f.many(2)
    created = f.take()
    more = f.deleted([ids[8], new[0]])
    batch = [gone[0], created[0], gone[1], gone[2], *edit, gone[3], created[1]]
    batch += back + [more[0]]
    answers = both(pair, [batch, [more[1]]])
    assert len(answers[0]) == len(batch)
    assert spy["delete"] and max(spy["delete"]) >= 2


def test_a_record_edited_on_the_server_is_kept_not_deleted(project, pair, spy):
    f = Flow(project)
    ids = f.many(6)
    made = f.take()
    first = f.structure + made
    for a in pair:
        send(a, first)
    gone = f.deleted(ids)
    mine = {e.entity_id: e for e in made if e.entity_type == "record"}
    both(pair, [[edit_entry(mine[ids[2]])]])
    answers = both(pair, [gone])
    statuses = {e.entity_id: r[1] for e, r in zip(gone, answers[0])}
    assert statuses[ids[2]] == "conflict"
    assert list(statuses.values()).count("applied") == 5


def test_a_record_with_children_is_settled_alone(project, pair, spy):
    f = Flow(project)
    enc = f.make("mine", "encounter", {"site": "a"})
    kid = f.make("mine", "recording", {"label": "x", "must": "m"}, str(enc))
    others = f.many(3)
    first = f.structure + f.take()
    for a in pair:
        send(a, first)
    gone = f.deleted([enc, kid] + others)
    # the parent's own entry alone (its child is not deleted with it)
    parent = dataclasses.replace(next(e for e in gone if e.entity_id == enc), op=None)
    rest = [e for e in gone if e.entity_id in set(others)]
    answers = both(pair, [[parent] + rest])
    assert answers[0][0][1] == "conflict"
    assert [r[1] for r in answers[0][1:]] == ["applied"] * 3
    assert spy["delete"] == [3]


def test_a_restore_of_a_record_whose_key_is_taken_is_refused(project, pair, spy):
    f = Flow(project)
    enc = f.make("mine", "encounter", {"site": "a"})
    r1 = f.make("mine", "recording", {"label": "x", "must": "m"}, str(enc))
    r2 = f.make("mine", "recording", {"label": "j", "must": "m"}, str(enc))
    made = f.take()
    first = f.structure + made
    for a in pair:
        send(a, first)
    gone = f.deleted([r1, r2])
    both(pair, [gone])
    taker = with_label(next(e for e in made if e.entity_id == r1), "x")
    both(pair, [[taker]])  # the label x is taken by another record now
    back = f.restored([r1, r2])
    answers = both(pair, [back])
    by = {e.entity_id: r[1] for e, r in zip(back, answers[0])}
    assert by[r1] == "rejected" and by[r2] == "applied"


def test_a_restore_flags_what_breaks_a_data_rule(project, pair, spy):
    f = Flow(project)
    enc = f.make("mine", "encounter", {"site": "a"})
    r1 = f.make("mine", "recording", {"label": "k", "must": "m"}, str(enc))
    first = f.structure + f.take()
    for a in pair:
        send(a, first)
    both(pair, [f.deleted([r1])])
    f.laptop.schema_svc.add_field("recording", "later", "string", required=True)
    f.laptop.commit()
    both(pair, [f.take()])  # a field becomes required while it is deleted
    answers = both(pair, [f.restored([r1])])
    assert answers[0][0][1] == "applied" and answers[0][0][3]  # flagged
    assert spy["restore"] == [1]


def test_a_stale_claimed_collection_is_not_kept(project, pair, spy):
    f = Flow(project)
    ids = f.many(4)
    first = f.structure + f.take()
    for a in pair:
        send(a, first)
    both(pair, [f.deleted(ids)])
    back = f.restored(ids)
    other = str(uuid.uuid4())
    for e in back:
        e.new_data = {**e.new_data, "dataset_id": other}
        e.old_data = e.old_data and {**e.old_data, "dataset_id": other}
    answers = both(pair, [back])
    assert answers[0]
    for a in pair:
        assert other not in str(rows(a)["audit_ext"])


def test_a_limited_caller_is_judged_as_one_at_a_time(project, pair, spy):
    f = Flow(project)
    sp_free = f.make("taxa", "species", {"latin": "free"})
    sp_held = f.make("taxa", "species", {"latin": "held"})
    f.make("secret", "encounter", {"site": "s", "seen": str(sp_held)})
    hidden = f.make("secret", "encounter", {"site": "h"})
    mine = f.many(3)
    first = f.structure + f.take()
    for a in pair:
        send(a, first)
    limited = []
    for a, bulk in zip(pair, (True, False)):

        def where(n, a=a):
            return a.dataset_svc.get(n).id

        perms = Permissions.of(
            p.READ,
            p.WRITE_RECORDS,
            p.DELETE,
            collections=[where("mine"), where("taxa")],
            read_collections=[where("mine"), where("taxa")],
        )
        ctx = build_context(dataclasses.replace(a.project, permissions=perms))
        ctx.authority_svc._bulk = bulk
        limited.append(ctx)
    ordered = [sp_free, sp_held, hidden] + mine
    by_id = {e.entity_id: e for e in f.deleted(ordered)}
    gone = [by_id[i] for i in ordered]
    absent = dataclasses.replace(gone[0], id=uuid.uuid4(), entity_id=uuid.uuid4())
    batch = gone + [absent]
    answers = [send(c, batch) for c in limited]
    assert answers[0] == answers[1]
    assert rows(pair[0]) == rows(pair[1])
    got = [(r[1], r[2]) for r in answers[0][0]]
    assert got[0][0] == "applied"
    assert got[1] == ("rejected", "Records you cannot see still reference this record.")
    assert [g[0] for g in got[3:6]] == ["applied"] * 3
    assert got[2][0] == "rejected" and got[-1][0] == "rejected"


def test_a_run_cut_at_its_size_still_guards_what_follows(project, pair, spy):
    from civex.services.sync_authority import RUN_MAX

    f = Flow(project)
    enc = f.make("mine", "encounter", {"site": "a"})
    f.make("mine", "recording", {"label": "x", "must": "m"}, str(enc))
    others = f.many(RUN_MAX + 40)
    first = f.structure + f.take()
    for a in pair:
        send(a, first)
    gone = f.deleted([enc] + others)
    parent = dataclasses.replace(next(e for e in gone if e.entity_id == enc), op=None)
    rest = [e for e in gone if e.entity_id != enc]
    batch = rest[: RUN_MAX + 20] + [parent] + rest[RUN_MAX + 20 :]
    answers = both(pair, [batch])
    assert answers[0][RUN_MAX + 20][1] == "conflict"  # a child is still live
    assert [r[1] for r in answers[0]].count("applied") == len(batch) - 1


def test_a_resent_change_inside_a_run_does_not_unguard_the_next(project, pair, spy):
    f = Flow(project)
    enc = f.make("mine", "encounter", {"site": "a"})
    f.make("mine", "recording", {"label": "x", "must": "m"}, str(enc))
    others = f.many(3)
    first = f.structure + f.take()
    for a in pair:
        send(a, first)
    gone = f.deleted([enc] + others)
    parent = dataclasses.replace(next(e for e in gone if e.entity_id == enc), op=None)
    rest = [e for e in gone if e.entity_id != enc]
    both(pair, [[rest[1]]])
    answers = both(pair, [[rest[0], rest[1], parent, rest[2]]])
    assert [r[1] for r in answers[0]] == ["applied", "applied", "conflict", "applied"]


def test_the_records_a_push_holds_follow_a_delete_restore_and_edit(project, pair):
    f = Flow(project)
    ids = f.many(3)
    made = f.take()
    for a in pair:
        send(a, f.structure + made)
    gone = f.deleted(ids)
    back = f.restored(ids)
    mine = {e.entity_id: e for e in made if e.entity_type == "record"}
    edit = edit_entry(mine[ids[0]])
    both(pair, [gone[:1] + back[:1]])  # (two kinds of run, one record)
    both(pair, [[edit]])
    for a in pair:
        a.commit()
        live = a._session.execute(
            text("SELECT count(*) FROM records WHERE deleted_at IS NULL")
        ).scalar()
        assert live == 3
