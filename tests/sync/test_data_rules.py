"""A record that breaks a data rule (a required field empty, a value outside its
field's restrictions) is taken in like any other and flagged: in the answer, as
an `unfit` item on the change that brought it. Only a value that is not of its
field's kind, a missing reference, a taken key and the like are still refused.

New records are judged in full; an edit by what it changed and the required
fields it emptied, so an old problem is never held against an unrelated edit.
The bulk path takes flagged records with the rest of their run."""

from __future__ import annotations

import pytest

from civex.domain.sync import SyncEntry
from civex.testing.peers import connect, device

from .test_bulk_push import Batch, _compare, count_bulk, rows, send, two_authorities


class Rules(Batch):
    """`encounter`: site (string, required), depth (0 to 100), kind (a, b)."""

    def __init__(self, project, authority_structure: bool = True) -> None:
        self.laptop = laptop = project("laptop")
        laptop.schema_svc.create("encounter")
        laptop.schema_svc.add_field("encounter", "site", "string", required=True)
        laptop.schema_svc.add_field(
            "encounter", "depth", "float", restrictions={"min": 0, "max": 100}
        )
        laptop.schema_svc.add_field(
            "encounter", "kind", "string", restrictions={"choices": ["a", "b"]}
        )
        laptop.dataset_svc.create("mine")
        laptop.commit()
        self.structure = self.take()
        self.ids = {
            f.name: str(f.id) for f in laptop.schema_svc.get("encounter").fields
        }

    def make(self, **values) -> SyncEntry:
        entry = self.add("mine", site="s", depth=1.0, kind="a")
        data = entry.new_data["data"]
        for name, value in values.items():
            if value is None:
                data.pop(self.ids[name], None)
            else:
                data[self.ids[name]] = value
        return entry

    def add(self, dataset, **values) -> SyncEntry:  # type: ignore[override]
        self.laptop.record_svc.add(dataset, "encounter", values)
        self.laptop.commit()
        [entry] = [e for e in self.take() if e.entity_type == "record"]
        return entry


def flags(answer) -> list[tuple[str, str, str]]:
    return [
        (c["kind"], c["field"], c["code"]) for c in answer[3] if c["kind"] == "unfit"
    ]


def test_records_breaking_rules_go_in_with_the_run_and_are_flagged(
    project, monkeypatch
):
    w = Rules(project)
    batch = [
        w.make(),
        w.make(site=None),  # required, missing
        w.make(depth=500.0),  # above its maximum
        w.make(kind="zzz"),  # not one of the choices
        w.make(site=None, depth=-1.0),  # two rules: two flags, one per field
        w.make(),
    ]
    fast, slow = two_authorities(project)
    calls = count_bulk(fast, monkeypatch)

    def no_settling(*a, **k):
        raise AssertionError("a flagged record left the bulk run")

    answers = {}
    for name, authority in (("fast", fast), ("slow", slow)):
        send(authority, w.structure)
        if name == "fast":
            monkeypatch.setattr(fast.authority_svc, "_settle", no_settling)
        answers[name], _ = send(authority, batch)
        if name == "fast":
            monkeypatch.undo()
    assert calls == [6]  # one run, flagged records included
    assert answers["fast"] == answers["slow"]
    assert rows(fast) == rows(slow)
    got = answers["fast"]
    assert [r[1] for r in got] == ["applied"] * 6
    f = {n: f"data.{i}" for n, i in w.ids.items()}
    assert flags(got[0]) == []
    assert flags(got[1]) == [("unfit", f["site"], "data")]
    assert flags(got[2]) == [("unfit", f["depth"], "data")]
    assert flags(got[3]) == [("unfit", f["kind"], "data")]
    assert sorted(flags(got[4])) == sorted(
        [("unfit", f["site"], "data"), ("unfit", f["depth"], "data")]
    )
    assert "maximum" in next(c for c in got[2][3])["message"]
    assert "required" in next(c for c in got[1][3])["message"]
    held = fast.record_svc.get(str(batch[2].entity_id)).data
    assert held["depth"] == 500.0  # kept as sent


def test_what_is_not_a_rule_is_still_refused(project, monkeypatch):
    w = Rules(project)
    bad = w.make(depth="deep")  # not a number: not a value of its field's kind
    ok = w.make(site=None)
    answers, calls = _compare(project, w.structure, [[bad, ok]], monkeypatch)
    assert answers == [["rejected", "applied"]]


def test_a_flagged_record_in_an_action_does_not_fail_the_action(project):
    w = Rules(project)
    entry = w.make(site=None)
    batch = [entry]
    answers, _ = _compare(project, w.structure, [batch])
    assert answers == [["applied"]]


def _tighten(authority, **change):
    authority.schema_svc.update_field("encounter", **change)
    authority.commit()


def test_an_edit_is_judged_by_what_it_changed(project):
    """The rules got stricter after the data was made: an edit that leaves an
    old problem alone is not flagged for it; one that sets a value outside the
    rule, or empties a required field, is."""
    w = Rules(project)
    authority = project("authority")
    send(authority, w.structure)
    made = [w.add("mine", site=n, depth=1.0, kind="a") for n in "abc"]
    send(authority, made)
    _tighten(authority, field_name="depth", restrictions={"min": 0, "max": 0.5})
    _tighten(authority, field_name="kind", required=True)
    for e in made:
        w.laptop.record_svc.update(
            str(e.entity_id), {"site": "x", "depth": 1.5, "kind": "a"}
        )
    w.laptop.commit()
    # (the laptop does not know the new rules: its own edits are fine to it)
    edits = {e.entity_id: e for e in w.take() if e.entity_type == "record"}
    answers, _ = send(authority, [edits[e.entity_id] for e in made])
    # every edit set depth 1.0, above the new maximum: changed, so flagged
    assert [flags(a) for a in answers] == [
        [("unfit", f"data.{w.ids['depth']}", "data")]
    ] * 3

    # An unrelated edit of the same record, still above the maximum, is not.
    w.laptop.record_svc.update(
        str(made[0].entity_id), {"site": "a2", "depth": 1.5, "kind": "a"}
    )
    w.laptop.commit()
    [unrelated] = [e for e in w.take() if e.entity_type == "record"]
    answers, _ = send(authority, [unrelated])
    assert [r[1] for r in answers] == ["applied"] and flags(answers[0]) == []

    # Emptying a required field is flagged (`kind` became required on the
    # authority; its records held a value).
    w.laptop.record_svc.update(str(made[1].entity_id), {"site": "b", "depth": 1.5})
    w.laptop.commit()
    [clears] = [e for e in w.take() if e.entity_type == "record"]
    answers, _ = send(authority, [clears])
    assert flags(answers[0]) == [("unfit", f"data.{w.ids['kind']}", "data")]


@pytest.fixture()
def laptop_and_phone(project, authority):
    laptop = device(project, authority, "laptop")
    laptop.schema_svc.create("call")
    laptop.schema_svc.add_field("call", "annotation", "string")
    laptop.schema_svc.add_field("call", "note", "string")
    laptop.dataset_svc.create("survey")
    laptop.commit()
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    return laptop, phone


def test_a_flag_reaches_the_pusher_shows_in_the_data_check_and_clears_when_fixed(
    laptop_and_phone, authority
):
    laptop, phone = laptop_and_phone
    made = laptop.record_svc.add(
        "survey", "call", {"annotation": "M (odd)", "note": "a"}
    )
    laptop.commit()
    phone.schema_svc.update_field(
        "call", "annotation", restrictions={"choices": ["Y", "M", "N"]}
    )
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()

    # Taken in: the authority and the other device hold it, nothing refused.
    assert authority.record_svc.get(str(made.id)).data["annotation"] == "M (odd)"
    assert [c for c in laptop.sync_svc.conflicts() if c.kind == "rejected"] == []
    state = laptop.sync_svc.record_sync(made.id)
    assert state.state == "unfit" and "must be one of" in (state.message or "")
    [item] = [c for c in laptop.sync_svc.conflicts() if c.kind == "unfit"]
    assert item.code == "data" and item.takes == ["theirs"]
    assert item.field_label == "Annotation"

    # Everyone holding it sees the flag as data: the quality view lists it.
    phone.sync_svc.sync()
    from civex.domain import quality
    from civex.domain.query import RecordQuery

    for ctx in (authority, phone):
        found, total = ctx.quality_svc.records_with(RecordQuery(), quality.BREAKS_RULE)
        assert total == 1 and found[0].record_id == str(made.id)
    assert not [c for c in phone.sync_svc.conflicts() if c.kind == "not_applied"]

    # An edit to something else does not clear it: the value still breaks.
    laptop.record_svc.update(str(made.id), {"annotation": "M (odd)", "note": "b"})
    laptop.commit()
    laptop.sync_svc.sync()
    assert laptop.sync_svc.record_sync(made.id).state == "unfit"

    # Fixing the value does, by itself.
    laptop.record_svc.update(str(made.id), {"annotation": "M", "note": "b"})
    laptop.commit()
    laptop.sync_svc.sync()
    assert [c for c in laptop.sync_svc.conflicts() if c.kind == "unfit"] == []
    assert laptop.sync_svc.record_sync(made.id).state == "synced"
