"""History entries that store only what changed: a delta must reproduce the thing
exactly, and must read back as the same diff the two whole snapshots give."""

from __future__ import annotations

import os
import random
from typing import Any

import pytest

from civex.domain.audit_diff import (
    apply_delta,
    diff_entry,
    entry_snapshots,
    identity,
    make_delta,
)

RECORD = {
    "id": "r1",
    "dataset_id": "d1",
    "schema_id": "s1",
    "parent_record_id": None,
    "data": {"f1": "a", "f2": 1, "f3": [1, 2], "f4": {"sha256": "x", "size": 3}},
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
    "deleted_at": None,
}


def edited(**changes: Any) -> dict[str, Any]:
    out = {**RECORD, "data": dict(RECORD["data"])}
    for key, value in changes.items():
        if key.startswith("f"):
            if value is _GONE:
                out["data"].pop(key, None)
            else:
                out["data"][key] = value
        else:
            out[key] = value
    return out


_GONE: Any = object()


@pytest.mark.parametrize(
    "new",
    [
        edited(f1="b"),
        edited(f1=None),
        edited(f1=_GONE),
        edited(f5="new"),
        edited(f2=1.0),  # equal in JSON, but a float now: kept exactly
        edited(f3=[1, 2, 3]),
        edited(f4={"sha256": "y", "size": 4}),
        edited(parent_record_id="r0", updated_at="2026-02-01T00:00:00+00:00"),
        edited(data={}),
        edited(data=None),
        {k: v for k, v in RECORD.items() if k != "data"},
        RECORD,
    ],
)
def test_a_delta_reproduces_the_new_snapshot_and_the_old_one(new):
    delta = make_delta(RECORD, new)
    assert apply_delta(RECORD, delta) == new
    assert apply_delta(new, delta, "before") == RECORD
    assert _exact(apply_delta(RECORD, delta)) == _exact(new)


def test_a_delta_holds_only_what_changed():
    delta = make_delta(RECORD, edited(f1="b"))
    assert delta == {"data.f1": {"before": "a", "after": "b"}}


def test_an_absent_value_is_told_from_a_null_one():
    assert make_delta(RECORD, edited(f1=None)) == {
        "data.f1": {"before": "a", "after": None}
    }
    assert make_delta(RECORD, edited(f1=_GONE)) == {"data.f1": {"before": "a"}}


def test_a_delta_entry_keeps_who_and_where_the_thing_is():
    new = edited(f1="b")
    assert identity(new) == {
        "id": "r1",
        "dataset_id": "d1",
        "schema_id": "s1",
        "parent_record_id": None,
    }


def test_an_entry_of_whole_snapshots_is_read_as_it_is():
    new = edited(f1="b")
    assert entry_snapshots(RECORD, new, None) == (RECORD, new)


@pytest.mark.parametrize("kind", ["record", "schema", "field", "dataset", "view"])
def test_a_delta_entry_reads_back_as_the_same_diff(kind):
    rng = random.Random(f"diff-{kind}")
    for _ in range(int(os.environ.get("CIVEX_DELTA_CASES", "300"))):
        old = _random_snapshot(rng, kind)
        new = _random_edit(rng, old, kind)
        whole = diff_entry(kind, "update", old, new)
        before, after = entry_snapshots(None, identity(new), make_delta(old, new))
        assert diff_entry(kind, "update", before, after) == whole, (old, new)
        assert apply_delta(old, make_delta(old, new)) == new


# -- random snapshots ---------------------------------------------------------------

_VALUES: list[Any] = [
    None,
    "",
    "a",
    "b",
    0,
    1,
    1.0,
    2.5,
    True,
    False,
    [],
    [1],
    ["a", "b"],
    {},
    {"sha256": "x", "filename": "f.txt", "size": 1},
    {"sha256": "x", "filename": "f.txt", "size": 1, "location": {"volume": "v"}},
    {"type": "Point", "coordinates": [1.0, 2.0]},
]


def _value(rng: random.Random) -> Any:
    return rng.choice(_VALUES)


def _random_snapshot(rng: random.Random, kind: str) -> dict[str, Any]:
    snap: dict[str, Any] = {"id": "x", "created_at": "t0", "updated_at": "t0"}
    if kind == "record":
        snap |= {"dataset_id": "d", "schema_id": "s", "parent_record_id": None}
        snap["data"] = {f"f{i}": _value(rng) for i in range(rng.randint(0, 6))}
    else:
        snap |= {f"a{i}": _value(rng) for i in range(rng.randint(0, 6))}
        snap["name"] = rng.choice(["n1", "n2"])
    return snap


def _random_edit(
    rng: random.Random, old: dict[str, Any], kind: str
) -> dict[str, Any]:
    new = {**old}
    if "data" in new and isinstance(new["data"], dict):
        new["data"] = dict(new["data"])
    for _ in range(rng.randint(0, 4)):
        roll = rng.random()
        target = new["data"] if kind == "record" and roll < 0.8 else new
        key = (
            f"f{rng.randint(0, 7)}"
            if target is not new
            else rng.choice(["a0", "a1", "a7", "name", "updated_at"])
        )
        if rng.random() < 0.2:
            target.pop(key, None)
        else:
            target[key] = _value(rng)
    if kind == "record" and rng.random() < 0.05:
        new["data"] = rng.choice([None, {}])
    return new


def _exact(value: Any) -> Any:
    """`value` with every number tagged by its type, so 1 and 1.0 differ."""
    if isinstance(value, dict):
        return {k: _exact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_exact(v) for v in value]
    return (type(value).__name__, value)
