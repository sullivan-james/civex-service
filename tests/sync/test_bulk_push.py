"""A pushed batch of new records is written in bulk; what each entry is
answered, and every row the authority keeps, is what settling the entries one
at a time gives (`SyncAuthorityService._bulk` off)."""

from __future__ import annotations

import dataclasses
import uuid

from sqlalchemy import text

from civex.domain.permissions import READ, WRITE_RECORDS, Permissions
from civex.domain.sync import SyncEntry
from civex.testing.peers import principal, wire

TABLES = {
    "records": "SELECT id, dataset_id, schema_id, parent_record_id, data, created_at, "
    "updated_at, deleted_at FROM records ORDER BY id",
    "audit_log": "SELECT id, action, entity_type, entity_id, old_data, new_data, delta, "
    "format, op_id, timestamp, actor, device, device_id, hlc, hub_seq, sync_state, "
    "apply_state FROM audit_log ORDER BY hub_seq, id",
    "sync_ops": "SELECT op_id, device_id, device_name, entity_type, entity_id, status, "
    "message, conflicts, hub_seq FROM sync_ops ORDER BY op_id",
    "file_references": "SELECT sha256, record_id, job_id, volume FROM file_references "
    "ORDER BY record_id, sha256",
    "record_references": "SELECT record_id, field_id, target_id FROM record_references "
    "ORDER BY record_id, field_id",
    "sync_meta": "SELECT head_seq, seeded_by FROM sync_meta",
}


def rows(ctx) -> dict[str, list]:
    ctx.commit()
    out = {
        name: [tuple(map(str, r)) for r in ctx._session.execute(text(sql)).all()]
        for name, sql in TABLES.items()
    }
    # What the authority writes itself (the settled state after a clash) has an
    # id, a time and a stamp of its own making.
    out["audit_log"] = [
        (r[:9] + ("-",) + r[10:13] + ("-",) + r[14:]) if r[10] == "sync" else r
        for r in out["audit_log"]
    ]
    out["audit_log"] = [
        ("-",) + r[1:] if r[10] == "sync" else r for r in out["audit_log"]
    ]
    return out


def send(authority, entries: list[SyncEntry], name: str = "laptop"):
    wired = [SyncEntry.from_dict(wire(e.to_dict())) for e in entries]
    result = authority.authority_svc.push(principal(authority, name), wired)
    authority.commit()
    return [
        (r.op_id, r.status, r.message, r.conflicts, r.hub_seq, r.replayed)
        for r in result.results
    ], result.head_seq


class Batch:
    """A laptop's structure and records, as entries to send to any authority."""

    def __init__(self, project) -> None:
        self.laptop = laptop = project("laptop")
        laptop.schema_svc.create("encounter")
        laptop.schema_svc.add_field("encounter", "site", "string")
        laptop.schema_svc.add_field("encounter", "depth", "float")
        laptop.schema_svc.add_field("encounter", "scan", "file")
        laptop.dataset_svc.create("mine")
        laptop.dataset_svc.create("theirs")
        laptop.commit()
        self.structure = self.take()
        self.file = laptop.file_svc.store_bytes(b"some bytes", "a.bin").to_dict()

    def take(self) -> list[SyncEntry]:
        entries = self.laptop.sync_repo.pending_entries(1000)
        self.laptop.sync_repo.mark_all_synced()
        self.laptop.commit()
        return entries

    def add(self, dataset: str, **values) -> SyncEntry:
        self.laptop.record_svc.add(dataset, "encounter", values)
        self.laptop.commit()
        [entry] = [e for e in self.take() if e.entity_type == "record"]
        return entry


def mixed(project) -> tuple[Batch, list[SyncEntry], list[SyncEntry]]:
    """Structure, then a batch of: new records (one citing a file), one sent
    twice, one made on the authority already (so this create meets it), one
    that is not valid, and one whose id is taken by an earlier entry of the
    batch."""
    b = Batch(project)
    held = b.add("mine", site="held", depth=1.0)
    first = [held]
    new1 = b.add("mine", site="a", depth=2.0)
    new2 = b.add("theirs", site="b", depth=3.0, scan=b.file)
    new3 = b.add("mine", site="c", depth=4.0)
    bad = b.add("mine", site="bad", depth=5.0)
    for k, v in bad.new_data["data"].items():
        bad.new_data["data"][k] = "not a number" if v == 5.0 else v
    meets = dataclasses.replace(
        held,
        id=new1.id.__class__("00000000-0000-4000-8000-000000000001"),
        new_data={
            **held.new_data,
            "data": {
                k: (9.0 if v == 1.0 else v) for k, v in held.new_data["data"].items()
            },
        },
    )
    again = dataclasses.replace(
        new3,
        id=new3.id.__class__("00000000-0000-4000-8000-000000000002"),
        new_data={
            **new3.new_data,
            "data": {
                k: ("changed" if v == "c" else v)
                for k, v in new3.new_data["data"].items()
            },
        },
    )
    batch = [new1, new2, new1, meets, new3, bad, again]
    return b, first, batch


def two_authorities(project, bulk_on: bool = True):
    fast, slow = project("authority-bulk"), project("authority-single")
    slow.authority_svc._bulk = False
    fast.authority_svc._bulk = bulk_on
    return fast, slow


def count_bulk(authority, monkeypatch) -> list[int]:
    calls: list[int] = []
    real = authority.sync_repo.insert_records

    def spy(states):
        calls.append(len(states))
        return real(states)

    monkeypatch.setattr(authority.sync_repo, "insert_records", spy)
    return calls


def test_a_mixed_batch_is_answered_and_kept_as_one_at_a_time(project, monkeypatch):
    b, first, batch = mixed(project)
    fast, slow = two_authorities(project)
    calls = count_bulk(fast, monkeypatch)
    for authority in (fast, slow):
        send(authority, b.structure + first)
    answers = [send(a, batch) for a in (fast, slow)]
    assert answers[0] == answers[1]
    statuses = [r[1] for r in answers[0][0]]
    assert statuses == [
        "applied",  # new
        "applied",  # new, cites a file
        "applied",  # the same entry sent again in the batch: answered as before
        "conflict",  # a create of a record that is here, with another value
        "applied",
        "rejected",
        "conflict",  # a second entry for a record the batch made
    ]
    assert answers[0][0][2][5] is True  # replayed
    assert rows(fast) == rows(slow)
    assert calls and max(calls) >= 2  # the new ones did go in together
    assert rows(fast)["file_references"]  # the cited file is counted


def test_a_whole_batch_sent_again_does_nothing(project, monkeypatch):
    b, first, batch = mixed(project)
    fast, _ = two_authorities(project)
    send(fast, b.structure + first)
    answered, head = send(fast, batch)
    before = rows(fast)
    calls = count_bulk(fast, monkeypatch)
    again, head_again = send(fast, batch)
    assert head_again == head
    assert rows(fast) == before
    assert not calls
    assert all(r[5] for r in again)  # every one answered as sent before
    assert [(r[0], r[1], r[4]) for r in again] == [(r[0], r[1], r[4]) for r in answered]


def test_each_entry_is_judged_by_the_collection_it_names(project, monkeypatch):
    b = Batch(project)
    mine = b.laptop.dataset_svc.get("mine")
    batch = [
        b.add("mine" if i % 2 == 0 else "theirs", site=f"s{i}", depth=float(i))
        for i in range(6)
    ]
    fast, slow = two_authorities(project)
    calls = count_bulk(fast, monkeypatch)
    for authority in (fast, slow):
        send(authority, b.structure)
        authority.authority_svc._policy = Permissions.of(
            READ, WRITE_RECORDS, collections=[mine.id]
        )
    answers = [send(a, batch) for a in (fast, slow)]
    assert answers[0] == answers[1]
    assert [r[1] for r in answers[0][0]] == [
        "applied",
        "rejected",
        "applied",
        "rejected",
        "applied",
        "rejected",
    ]
    assert rows(fast) == rows(slow)
    assert calls == [
        3
    ]  # the three it may write went in together, the refusals between them left no gap


def test_a_record_the_database_refuses_is_settled_on_its_own(project, monkeypatch):
    """If the bulk write fails, nothing of the run stays and each entry is
    settled alone: a good one still goes in."""
    b = Batch(project)
    batch = [b.add("mine", site=f"s{i}", depth=float(i)) for i in range(4)]
    fast, slow = two_authorities(project)
    for authority in (fast, slow):
        send(authority, b.structure)

    def refuse(states):
        from civex.domain.exceptions import ValidationError

        raise ValidationError("the database said no")

    monkeypatch.setattr(fast.sync_repo, "insert_records", refuse)
    answers = [send(a, batch) for a in (fast, slow)]
    assert answers[0] == answers[1]
    assert rows(fast) == rows(slow)


def test_a_schema_with_a_uniqueness_key_is_checked_against_the_batch(project):
    b = Batch(project)
    b.laptop.schema_svc.create("sample")
    b.laptop.schema_svc.add_field("sample", "tag", "string")
    b.laptop.schema_svc.set_unique_keys("sample", [["tag"]])
    b.laptop.commit()
    structure = b.take()
    entries = []
    for tag in ("x", "y"):
        b.laptop.record_svc.add("mine", "sample", {"tag": tag})
        b.laptop.commit()
        entries += [e for e in b.take() if e.entity_type == "record"]
    entries.append(
        dataclasses.replace(
            entries[0],
            id=uuid.uuid4(),
            entity_id=(same := uuid.uuid4()),
            new_data={**entries[0].new_data, "id": str(same)},
        )
    )
    fast, slow = two_authorities(project)
    for authority in (fast, slow):
        send(authority, b.structure + structure)
    answers = [send(a, entries) for a in (fast, slow)]
    assert answers[0] == answers[1]
    assert [r[1] for r in answers[0][0]] == ["applied", "applied", "rejected"]
    assert rows(fast) == rows(slow)


def again(entry: SyncEntry) -> SyncEntry:
    """Another record, new in every id, holding the same values."""
    fresh = uuid.uuid4()
    return dataclasses.replace(
        entry,
        id=uuid.uuid4(),
        entity_id=fresh,
        new_data={**entry.new_data, "id": str(fresh)},
    )


class Family:
    """Structure with parents, references and a uniqueness key, and records of
    it made on a laptop as entries to send."""

    def __init__(self, project) -> None:
        self.laptop = laptop = project("laptop")
        laptop.schema_svc.create("species")
        laptop.schema_svc.add_field("species", "latin", "string")
        laptop.schema_svc.create("encounter")
        laptop.schema_svc.add_field("encounter", "site", "string")
        laptop.schema_svc.add_field(
            "encounter", "seen", "reference", restrictions={"schema": "species"}
        )
        laptop.schema_svc.create("recording", parent="encounter")
        laptop.schema_svc.add_field("recording", "label", "string")
        laptop.schema_svc.set_unique_keys("recording", [["label"]])
        laptop.schema_svc.create("clip", parent="recording")
        laptop.schema_svc.add_field("clip", "secs", "float")
        laptop.dataset_svc.create("mine")
        laptop.dataset_svc.create("theirs")
        laptop.dataset_svc.create("taxa", scope="global")
        laptop.commit()
        self.structure = self.take()

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


def _compare(project, structure, batches, monkeypatch=None, policy=None):
    """Send the same batches to a bulk and to a one-at-a-time authority."""
    fast, slow = two_authorities(project)
    calls = count_bulk(fast, monkeypatch) if monkeypatch else []
    for authority in (fast, slow):
        send(authority, structure)
        if policy is not None:
            authority.authority_svc._policy = policy
    out = []
    for batch in batches:
        answers = [send(a, batch) for a in (fast, slow)]
        assert answers[0] == answers[1]
        assert rows(fast) == rows(slow)
        out.append([r[1] for r in answers[0][0]])
    return out, calls


def test_a_chain_of_parents_in_one_batch_goes_in_together(project, monkeypatch):
    f = Family(project)
    enc = f.add("mine", "encounter", {"site": "a"})
    rec1 = f.add("mine", "recording", {"label": "x"}, str(enc.entity_id))
    rec2 = f.add("mine", "recording", {"label": "y"}, str(enc.entity_id))
    clip = f.add("mine", "clip", {"secs": 1.0}, str(rec1.entity_id))
    enc2 = f.add("theirs", "encounter", {"site": "b"})
    rec3 = f.add("theirs", "recording", {"label": "x"}, str(enc2.entity_id))
    statuses, calls = _compare(
        project, f.structure, [[enc, rec1, rec2, clip, enc2, rec3]], monkeypatch
    )
    assert statuses == [["applied"] * 6]
    assert calls == [6]  # parents and children, in one write


def test_a_parent_from_an_earlier_push(project, monkeypatch):
    f = Family(project)
    enc = f.add("mine", "encounter", {"site": "a"})
    kids = [
        f.add("mine", "recording", {"label": f"r{i}"}, str(enc.entity_id))
        for i in range(3)
    ]
    statuses, calls = _compare(project, f.structure, [[enc], kids], monkeypatch)
    assert statuses == [["applied"], ["applied"] * 3]
    assert calls == [1, 3]


def test_a_missing_parent_is_refused_as_before(project, monkeypatch):
    f = Family(project)
    enc = f.add("mine", "encounter", {"site": "a"})
    rec = f.add("mine", "recording", {"label": "x"}, str(enc.entity_id))
    orphan = f.add("mine", "recording", {"label": "y"}, str(enc.entity_id))
    orphan.new_data["parent_record_id"] = str(uuid.uuid4())
    late = f.add("mine", "recording", {"label": "z"}, str(enc.entity_id))
    # the child before its parent, one under a parent that was never sent, and
    # one that is fine
    statuses, _ = _compare(
        project, f.structure, [[rec, orphan, enc, late]], monkeypatch
    )
    assert statuses[0][0] != "applied"
    assert statuses[0][1] != "applied"
    assert statuses[0][2:] == ["applied", "applied"]


def test_a_parent_the_batch_refused_leaves_its_children_refused(project):
    f = Family(project)
    enc = f.add("mine", "encounter", {"site": "a"})
    bad = dataclasses.replace(
        enc, new_data={**enc.new_data, "dataset_id": str(uuid.uuid4())}
    )
    rec = f.add("mine", "recording", {"label": "x"}, str(enc.entity_id))
    statuses, _ = _compare(project, f.structure, [[bad, rec]])
    assert "applied" not in statuses[0]


def test_a_child_of_another_schemas_record_is_refused_as_before(project):
    f = Family(project)
    enc = f.add("mine", "encounter", {"site": "a"})
    rec = f.add("mine", "recording", {"label": "x"}, str(enc.entity_id))
    clip = f.add("mine", "clip", {"secs": 1.0}, str(rec.entity_id))
    wrong = dataclasses.replace(
        clip,
        id=uuid.uuid4(),
        entity_id=(new := uuid.uuid4()),
        new_data={
            **clip.new_data,
            "id": str(new),
            "parent_record_id": str(enc.entity_id),
        },
    )
    statuses, _ = _compare(project, f.structure, [[enc, rec, clip, wrong]])
    assert statuses[0][:3] == ["applied"] * 3
    assert statuses[0][3] != "applied"


def test_references_to_the_batch_to_stored_records_and_to_what_is_missing(
    project, monkeypatch
):
    f = Family(project)
    sp1 = f.add("taxa", "species", {"latin": "orca"})
    sp2 = f.add("taxa", "species", {"latin": "minke"})
    stored = f.add("mine", "encounter", {"site": "s", "seen": str(sp1.entity_id)})
    in_batch = f.add("mine", "encounter", {"site": "t", "seen": str(sp2.entity_id)})
    forward = f.add("mine", "encounter", {"site": "u", "seen": str(sp1.entity_id)})
    later = f.add("taxa", "species", {"latin": "later"})
    missing = f.add("mine", "encounter", {"site": "v", "seen": str(sp1.entity_id)})
    seen_key = next(
        k for k, v in stored.new_data["data"].items() if v == str(sp1.entity_id)
    )
    forward.new_data["data"][seen_key] = str(later.entity_id)
    missing.new_data["data"][seen_key] = str(uuid.uuid4())
    other_dataset = f.add(
        "theirs", "encounter", {"site": "w", "seen": str(sp1.entity_id)}
    )
    statuses, calls = _compare(
        project,
        f.structure,
        [[sp1], [stored, sp2, in_batch, forward, later, missing, other_dataset]],
        monkeypatch,
    )
    # a target in a global collection, in the batch or held, is fine; one made
    # after the record that cites it, or one that is not there, is not
    assert statuses[1] == [
        "applied",
        "applied",
        "applied",
        "rejected",
        "applied",
        "rejected",
        "applied",
    ]
    assert max(calls) >= 3


def test_a_uniqueness_key_is_judged_within_the_parent(project, monkeypatch):
    f = Family(project)
    e1 = f.add("mine", "encounter", {"site": "a"})
    e2 = f.add("mine", "encounter", {"site": "b"})
    ok1 = f.add("mine", "recording", {"label": "x"}, str(e1.entity_id))
    ok2 = f.add("mine", "recording", {"label": "x"}, str(e2.entity_id))  # other parent
    dup = again(ok1)  # same label, same parent
    ok3 = f.add("mine", "recording", {"label": "y"}, str(e1.entity_id))
    statuses, calls = _compare(
        project, f.structure, [[e1, e2, ok1, ok2, dup, ok3]], monkeypatch
    )
    assert statuses == [
        ["applied", "applied", "applied", "applied", "rejected", "applied"]
    ]
    assert calls and calls[0] >= 4


def test_a_uniqueness_key_taken_by_stored_data(project, monkeypatch):
    f = Family(project)
    e1 = f.add("mine", "encounter", {"site": "a"})
    first = f.add("mine", "recording", {"label": "x"}, str(e1.entity_id))
    clash = again(first)
    fine = f.add("mine", "recording", {"label": "z"}, str(e1.entity_id))
    statuses, _ = _compare(
        project, f.structure, [[e1, first], [clash, fine]], monkeypatch
    )
    assert statuses == [["applied", "applied"], ["rejected", "applied"]]


def test_children_are_judged_by_the_collection_they_name(project, monkeypatch):
    f = Family(project)
    mine = f.laptop.dataset_svc.get("mine")
    e1 = f.add("mine", "encounter", {"site": "a"})
    e2 = f.add("theirs", "encounter", {"site": "b"})
    r1 = f.add("mine", "recording", {"label": "x"}, str(e1.entity_id))
    r2 = f.add("theirs", "recording", {"label": "x"}, str(e2.entity_id))
    r3 = f.add("mine", "recording", {"label": "y"}, str(e1.entity_id))
    statuses, calls = _compare(
        project,
        f.structure,
        [[e1, e2, r1, r2, r3]],
        monkeypatch,
        policy=Permissions.of(READ, WRITE_RECORDS, collections=[mine.id]),
    )
    assert statuses == [["applied", "rejected", "applied", "rejected", "applied"]]
    assert calls == [3]


def test_a_number_and_the_same_number_as_text_share_a_key(project):
    f = Family(project)
    f.laptop.schema_svc.create("count")
    f.laptop.schema_svc.add_field("count", "n", "float")
    f.laptop.schema_svc.set_unique_keys("count", [["n"]])
    f.laptop.commit()
    structure = f.take()
    f.laptop.record_svc.add("mine", "count", {"n": 30.0})
    f.laptop.commit()
    [a] = [e for e in f.take() if e.entity_type == "record"]
    b = again(a)
    key = next(iter(b.new_data["data"]))
    b.new_data["data"] = {key: "30"}
    statuses, _ = _compare(project, f.structure + structure, [[a, b]])
    assert statuses == [["applied", "rejected"]]


def test_a_resent_push_with_keys_does_not_read_again_for_each(project, monkeypatch):
    f = Family(project)
    e1 = f.add("mine", "encounter", {"site": "a"})
    kids = [
        f.add("mine", "recording", {"label": f"r{i}"}, str(e1.entity_id))
        for i in range(30)
    ]
    fast, _ = two_authorities(project)
    send(fast, f.structure)
    send(fast, [e1] + kids)
    reads = []
    real = fast.sync_repo  # noqa: F841
    from civex.repositories.local.record_repo import LocalRecordRepository

    seen = LocalRecordRepository.any_key_match

    def spy(self, *a, **k):
        reads.append(1)
        return seen(self, *a, **k)

    monkeypatch.setattr(LocalRecordRepository, "any_key_match", spy)
    send(fast, [e1] + kids)
    assert not reads
