"""A caller who sees only some collections is written in bulk too, and what
each entry is answered, and every row kept, is what settling them one at a
time gives; a hidden parent, record or file is answered exactly as a missing
one (same words, same code, same number of statements)."""

from __future__ import annotations

import dataclasses
import uuid

from sqlalchemy import event

from civex.context import build_context
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.domain.sync import SyncEntry
from civex.testing.peers import principal, wire

from .test_bulk_push import again, deleted, rows, send


class World:
    """Structure with a parent chain, a reference and a file field, in
    collections the limited caller reads (`mine`, `taxa`), writes without
    reading (`theirs`, `vault`) and does not touch (`secret`)."""

    def __init__(self, project) -> None:
        self.project = project
        self.laptop = laptop = project("laptop")
        laptop.schema_svc.create("species")
        laptop.schema_svc.add_field("species", "latin", "string")
        laptop.schema_svc.create("encounter")
        laptop.schema_svc.add_field("encounter", "site", "string")
        laptop.schema_svc.add_field(
            "encounter", "seen", "reference", restrictions={"schema": "species"}
        )
        laptop.schema_svc.add_field("encounter", "scan", "file")
        laptop.schema_svc.create("recording", parent="encounter")
        laptop.schema_svc.add_field("recording", "label", "string")
        laptop.schema_svc.set_unique_keys("recording", [["label"]])
        for name in ("mine", "theirs", "secret"):
            laptop.dataset_svc.create(name)
        laptop.dataset_svc.create("taxa", scope="global")
        laptop.dataset_svc.create("vault", scope="global")
        laptop.commit()
        self.structure = self.take()
        self.files = [
            laptop.file_svc.store_bytes(bytes([i]) * 9, f"f{i}.bin").to_dict()
            for i in range(6)
        ]

    def take(self) -> list[SyncEntry]:
        entries = self.laptop.sync_repo.pending_entries(1000)
        self.laptop.sync_repo.mark_all_synced()
        self.laptop.commit()
        return entries

    def add(self, dataset, schema, values, parent=None) -> SyncEntry:
        made = self.laptop.record_svc.add(
            dataset, schema, values, parent_record_id=parent
        )
        self.laptop.commit()
        [entry] = [e for e in self.take() if e.entity_type == "record"]
        assert entry.entity_id == made.id
        return entry

    def under(self, dataset, label, parent_id) -> SyncEntry:
        """A recording in `dataset` sent as sitting under `parent_id`, a record
        the laptop does not hold there (made under a stand-in, then re-aimed)."""
        if not hasattr(self, "stand_in"):
            self.stand_in = {}
        if dataset not in self.stand_in:
            self.stand_in[dataset] = self.add(
                dataset, "encounter", {"site": "stand-in"}
            )
        entry = self.add(
            dataset,
            "recording",
            {"label": label},
            str(self.stand_in[dataset].entity_id),
        )
        entry.new_data["parent_record_id"] = str(parent_id)
        return entry

    def delete(self, entry: SyncEntry) -> SyncEntry:
        self.laptop.record_svc.delete(str(entry.entity_id), force=True)
        self.laptop.commit()
        [gone] = [
            e
            for e in self.take()
            if e.entity_type == "record" and e.entity_id == entry.entity_id
        ]
        return gone

    def pair(self):
        """Two authorities holding the same structure, and a limited caller
        on each (one writing in bulk, one a change at a time)."""
        out = []
        for name in ("authority-bulk", "authority-single"):
            authority = self.project(name)
            send(authority, self.structure)
            out.append(authority)
        return out

    def limited(self, authority, bulk: bool):
        def where(name):
            return authority.dataset_svc.get(name).id

        perms = Permissions.of(
            p.READ,
            p.WRITE_RECORDS,
            p.DELETE,
            p.ADD_FILES,
            collections=[where(n) for n in ("mine", "taxa")],
            read_collections=[where(n) for n in ("mine", "taxa")],
        )
        ctx = build_context(dataclasses.replace(authority.project, permissions=perms))
        ctx.authority_svc._bulk = bulk
        return ctx


def push(ctx, entries, name="limited"):
    wired = [SyncEntry.from_dict(wire(e.to_dict())) for e in entries]
    result = ctx.authority_svc.push(principal(ctx, name), wired)
    ctx.commit()
    return [
        (r.op_id, r.status, r.message, r.conflicts, r.hub_seq, r.replayed)
        for r in result.results
    ], result.head_seq


def bulk_calls(ctx, monkeypatch) -> list[int]:
    calls: list[int] = []
    real = ctx.sync_repo.insert_records

    def spy(states):
        calls.append(len(states))
        return real(states)

    monkeypatch.setattr(ctx.sync_repo, "insert_records", spy)
    return calls


def compare(world, seed, batches, monkeypatch=None):
    """Seed both authorities (as an unrestricted device), then send the same
    batches as a limited caller to the bulk and the one-at-a-time one."""
    fast, slow = world.pair()
    for a in (fast, slow):
        send(a, seed, name="seeder")
    ctxs = [world.limited(fast, True), world.limited(slow, False)]
    calls = bulk_calls(ctxs[0], monkeypatch) if monkeypatch else []
    out = []
    try:
        for batch in batches:
            answers = [push(c, batch) for c in ctxs]
            assert answers[0] == answers[1]
            assert rows(fast) == rows(slow)
            out.append(answers[0][0])
    finally:
        for c in ctxs:
            c.close()
    return out, calls


def test_a_run_of_new_records_goes_in_in_bulk_for_a_limited_caller(
    project, monkeypatch
):
    w = World(project)
    sp = w.add("taxa", "species", {"latin": "orca"})
    batch = [
        w.add("mine", "encounter", {"site": f"s{i}", "seen": str(sp.entity_id)})
        for i in range(6)
    ]
    batch += [w.add("mine", "encounter", {"site": "w", "scan": w.files[0]})]
    batch += [deleted(w.add("mine", "encounter", {"site": "gone"}))]
    out, calls = compare(w, [sp], [batch], monkeypatch)
    assert [r[1] for r in out[0]] == ["applied"] * len(batch)
    assert max(calls) >= len(batch)  # not through the settled-alone fallback


def test_a_hidden_parent_is_refused_as_a_missing_one(project, monkeypatch):
    w = World(project)
    seen_enc = w.add("mine", "encounter", {"site": "seen"})
    hidden_enc = w.add("secret", "encounter", {"site": "hidden"})
    written_enc = w.add("theirs", "encounter", {"site": "written"})
    under_seen = w.add("mine", "recording", {"label": "a"}, str(seen_enc.entity_id))
    under_hidden = w.under("mine", "b", hidden_enc.entity_id)
    under_written = w.under("mine", "c", written_enc.entity_id)
    under_missing = w.add("mine", "recording", {"label": "d"}, str(seen_enc.entity_id))
    under_missing.new_data["parent_record_id"] = str(uuid.uuid4())
    # a parent made in the push in a collection the caller cannot see
    made_hidden = w.add("theirs", "encounter", {"site": "made"})
    under_made = w.under("theirs", "e", made_hidden.entity_id)
    made_seen = w.add("mine", "encounter", {"site": "made seen"})
    under_made_seen = w.add(
        "mine", "recording", {"label": "f"}, str(made_seen.entity_id)
    )
    batch = [
        under_seen, under_hidden, under_written, under_missing, made_hidden,
        under_made, made_seen, under_made_seen,
    ]  # fmt: skip
    out, calls = compare(
        w, [seen_enc, hidden_enc, written_enc], [batch, batch], monkeypatch
    )
    first = out[0]
    assert [r[1] for r in first] == [
        "applied", "rejected", "rejected", "rejected", "rejected",
        "rejected", "applied", "applied",
    ]  # fmt: skip
    assert all(r[5] for r in out[1])  # sent again: answered, not done again
    assert first[1][2] == first[3][2] == first[2][2]  # (5: not a collection it sees)
    assert max(calls) >= 2


def test_a_hidden_reference_is_refused_as_a_missing_one(project, monkeypatch):
    w = World(project)
    seen_sp = w.add("taxa", "species", {"latin": "orca"})
    hidden_sp = w.add("vault", "species", {"latin": "secret"})
    cites = lambda target: w.add(  # noqa: E731
        "mine", "encounter", {"site": "x", "seen": str(target)}
    )
    ok = cites(seen_sp.entity_id)
    to_hidden = cites(seen_sp.entity_id)
    key = next(k for k, v in ok.new_data["data"].items() if v == str(seen_sp.entity_id))
    to_hidden.new_data["data"][key] = str(hidden_sp.entity_id)
    to_missing = cites(seen_sp.entity_id)
    to_missing.new_data["data"][key] = str(uuid.uuid4())
    # a species made in the run, where the caller cannot read, then cited
    made_hidden = w.add("vault", "species", {"latin": "made"})
    to_made = cites(seen_sp.entity_id)
    to_made.new_data["data"][key] = str(made_hidden.entity_id)
    made_seen = w.add("taxa", "species", {"latin": "made seen"})
    to_made_seen = cites(seen_sp.entity_id)
    to_made_seen.new_data["data"][key] = str(made_seen.entity_id)
    batch = [ok, to_hidden, to_missing, made_hidden, to_made, made_seen, to_made_seen]
    out, calls = compare(w, [seen_sp, hidden_sp], [batch], monkeypatch)
    got = out[0]
    assert [r[1] for r in got] == [
        "applied", "rejected", "rejected", "rejected", "rejected", "applied", "applied",
    ]  # fmt: skip
    assert max(calls) >= 2

    def said(r, target):
        return r[2].replace(str(target), "<id>")

    assert said(got[1], hidden_sp.entity_id) == said(
        got[2], to_missing.new_data["data"][key]
    )
    assert got[1][3] == got[2][3]


def test_a_hidden_file_is_refused_as_one_not_here(project, monkeypatch):
    w = World(project)
    f = w.files
    # f0 is used by a record the caller cannot read, f1 by one it can, f2 by
    # nothing
    hidden_use = w.add("secret", "encounter", {"site": "h", "scan": f[0]})
    seen_use = w.add("mine", "encounter", {"site": "s", "scan": f[1]})
    cites = lambda ds, file: w.add(ds, "encounter", {"site": "c", "scan": file})  # noqa: E731
    batch = [
        cites("mine", f[0]),  # used only by a hidden record
        cites("mine", f[1]),
        cites("mine", f[2]),
        cites("mine", f[2]),  # (the same, a second time)
        cites("theirs", f[3]),  # (a collection it cannot see)
        cites("mine", f[3]),
        cites("mine", f[4]),
        cites("theirs", f[4]),
        deleted(cites("mine", f[5])),  # a deleted record's use
        cites("mine", f[5]),
        cites("mine", f[0]),
    ]
    out, calls = compare(w, [hidden_use, seen_use], [batch, batch], monkeypatch)
    got = out[0]
    assert [r[1] for r in got] == [
        "rejected", "applied", "applied", "applied", "rejected", "applied",
        "applied", "rejected", "applied", "applied", "rejected",
    ]  # fmt: skip
    assert got[0][2] == got[10][2] == "That file is not available."
    assert got[0][3] == got[10][3]
    assert max(calls) >= 3


def test_a_file_known_to_nothing_is_the_same_whether_hidden_or_not(project):
    # the same refusal for a file a hidden record holds as for a file that is
    # in no record at all, never a different count of questions
    w = World(project)
    hidden_use = w.add("secret", "encounter", {"site": "h", "scan": w.files[0]})
    [auth] = [w.pair()[0]]
    send(auth, [hidden_use], name="seeder")
    ctx = w.limited(auth, True)
    seen = {"queries": 0}
    engine = ctx._session.get_bind()

    @event.listens_for(engine, "before_cursor_execute")
    def count(*args):
        seen["queries"] += 1

    try:
        counts = []
        for sha_file in (w.files[0], w.files[1]):
            seen["queries"] = 0
            entry = w.add("mine", "encounter", {"site": "c", "scan": sha_file})
            push(ctx, [entry])
            counts.append(seen["queries"])
    finally:
        event.remove(engine, "before_cursor_execute", count)
        ctx.close()
    assert counts[0] <= counts[1]  # the refusal is not the dearer answer
    assert counts[1] - counts[0] <= 12  # (an applied one writes more rows)


def test_hidden_and_missing_cost_the_same_statements(project):
    w = World(project)
    sp = w.add("taxa", "species", {"latin": "orca"})
    hidden_enc = w.add("secret", "encounter", {"site": "hidden"})
    hidden_sp = w.add("vault", "species", {"latin": "secret"})
    seen_enc = w.add("mine", "encounter", {"site": "seen"})
    fast, _ = w.pair()
    send(fast, [sp, hidden_enc, hidden_sp, seen_enc], name="seeder")
    ctx = w.limited(fast, True)
    engine = ctx._session.get_bind()
    n = {"q": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def count(*args):
        n["q"] += 1

    def attempt(kind: str, target: uuid.UUID) -> tuple[int, tuple]:
        if kind == "parent":
            e = w.add(
                "mine",
                "recording",
                {"label": uuid.uuid4().hex},
                str(seen_enc.entity_id),
            )
            e.new_data["parent_record_id"] = str(target)
        else:
            e = w.add(
                "mine",
                "encounter",
                {"site": uuid.uuid4().hex, "seen": str(sp.entity_id)},
            )
            key = next(
                k for k, v in e.new_data["data"].items() if v == str(sp.entity_id)
            )
            e.new_data["data"][key] = str(target)
        n["q"] = 0
        [(_, status, message, conflicts, *_)] = push(ctx, [e])[0]
        said = (status, message.replace(str(target), "<id>"), conflicts)
        return n["q"], said

    try:
        for kind, hidden in (("parent", hidden_enc), ("ref", hidden_sp)):
            attempt(kind, uuid.uuid4())  # (the first of a kind warms what is read once)
            a = attempt(kind, hidden.entity_id)
            b = attempt(kind, uuid.uuid4())
            assert a == b, kind
            assert a[1][0] == "rejected"
    finally:
        event.remove(engine, "before_cursor_execute", count)
        ctx.close()


def test_deleting_what_a_hidden_record_points_at_is_refused_in_a_mixed_run(
    project, monkeypatch
):
    w = World(project)
    sp = w.add("taxa", "species", {"latin": "orca"})
    sp2 = w.add("taxa", "species", {"latin": "minke"})
    holder = w.add("secret", "encounter", {"site": "holds", "seen": str(sp.entity_id)})
    mine = w.add("mine", "encounter", {"site": "mine", "seen": str(sp2.entity_id)})
    drop_sp, drop_sp2 = w.delete(sp), w.delete(sp2)
    new = [w.add("mine", "encounter", {"site": f"n{i}"}) for i in range(4)]
    batch = [new[0], new[1], drop_sp, new[2], drop_sp2, new[3]]
    out, calls = compare(w, [sp, sp2, holder, mine], [batch, batch], monkeypatch)
    got = out[0]
    # a hidden record still points at the first: refused whatever the rest do
    assert got[2][1] == "rejected"
    assert got[2][2] == "Records you cannot see still reference this record."
    assert [got[i][1] for i in (0, 1, 3, 5)] == ["applied"] * 4
    assert all(r[5] for r in out[1])
    assert max(calls) >= 2


def test_a_collection_that_hidden_records_reference_cannot_go(project, monkeypatch):
    w = World(project)
    sp = w.add("taxa", "species", {"latin": "orca"})
    holder = w.add("secret", "encounter", {"site": "holds", "seen": str(sp.entity_id)})
    new = [w.add("mine", "encounter", {"site": f"n{i}"}) for i in range(3)]
    taxa = next(
        e
        for e in w.structure
        if e.entity_type == "dataset" and e.new_data.get("name") == "taxa"
    )
    drop = dataclasses.replace(
        taxa,
        id=uuid.uuid4(),
        action="delete",
        old_data=taxa.new_data,
        new_data=None,
    )
    batch = [new[0], new[1], drop, new[2]]
    out, _ = compare(w, [sp, holder], [batch], monkeypatch)
    got = out[0]
    assert got[2][1] == "rejected"
    assert [got[i][1] for i in (0, 1, 3)] == ["applied"] * 3


def test_a_mixed_run_of_everything(project, monkeypatch):
    w = World(project)
    f = w.files
    sp = w.add("taxa", "species", {"latin": "orca"})
    hidden_sp = w.add("vault", "species", {"latin": "secret"})
    enc = w.add("mine", "encounter", {"site": "e"})
    hidden_enc = w.add("secret", "encounter", {"site": "h", "scan": f[0]})
    plain = w.add("mine", "encounter", {"site": "p", "seen": str(sp.entity_id)})
    key = next(k for k, v in plain.new_data["data"].items() if v == str(sp.entity_id))
    r1 = w.add("mine", "recording", {"label": "r1"}, str(enc.entity_id))
    batch = [
        plain,
        again(plain),
        r1,
        w.under("mine", "r2", hidden_enc.entity_id),
        w.add("mine", "encounter", {"site": "q", "scan": f[0]}),  # hidden file
        w.add("mine", "encounter", {"site": "q2", "scan": f[1]}),
        deleted(w.add("mine", "recording", {"label": "r3"}, str(enc.entity_id))),
        again(r1),  # same key
    ]
    batch[1].new_data["data"] = {
        **batch[1].new_data["data"],
        key: str(hidden_sp.entity_id),
    }
    out, calls = compare(
        w, [sp, hidden_sp, enc, hidden_enc], [batch, batch], monkeypatch
    )
    assert all(r[5] for r in out[1])
    statuses = [r[1] for r in out[0]]
    assert statuses[:3] == ["applied", "rejected", "applied"]
    assert statuses[3:5] == ["rejected", "rejected"]
    assert max(calls) >= 2
