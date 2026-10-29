"""What devices agree on is a project one machine could hold (the invariants
scenario).

Three devices delete and restore schemas and collections, add and drop unique
keys, rename, add and delete fields, edit naming templates, and add, edit,
delete and restore records (some under a parent), syncing at random through a
network that drops replies. Afterwards every rule a single machine enforces
must hold on the authority (`broken_rules`), and every copy must agree with it
except for what has an open review item on that device."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

from civex.domain.exceptions import CivexError
from civex.domain.sync import SyncError
from civex.domain.templating import referenced_names

from civex.testing.convergence import differences, quiesce
from civex.testing.peers import connect, device, flaky, snapshots


def populate(ctx) -> None:
    ctx.schema_svc.create("encounter")
    ctx.schema_svc.add_field("encounter", "site", "string")
    ctx.schema_svc.add_field("encounter", "depth", "float")
    ctx.schema_svc.create("sample", parent="encounter")
    ctx.schema_svc.add_field("sample", "label", "string")
    ctx.schema_svc.create("note")
    ctx.schema_svc.add_field("note", "text", "string")
    ctx.dataset_svc.create("study")
    ctx.dataset_svc.create("extra")
    for n in range(3):
        e = ctx.record_svc.add("study", "encounter", {"site": f"s{n}", "depth": 1.0})
        ctx.record_svc.add(
            "study", "sample", {"label": f"l{n}"}, parent_record_id=str(e.id)
        )
    ctx.record_svc.add("extra", "note", {"text": "hello"})
    ctx.commit()


def _live_records(ctx, schema: str) -> list:
    try:
        sid = str(ctx.schema_svc.get(schema).id)
    except CivexError:
        return []
    return [
        r
        for r in ctx.sync_repo.snapshots_page("record", None, 1000)
        if r["schema_id"] == sid and not r["deleted_at"]
    ]


def _deleted(ctx, kind: str) -> list[dict[str, Any]]:
    return [
        s for s in ctx.sync_repo.snapshots_page(kind, None, 1000) if s["deleted_at"]
    ]


def _field_names(ctx, schema: str) -> list[str]:
    try:
        return [f.name for f in ctx.schema_svc.get(schema).fields]
    except CivexError:
        return []


def act(ctx, rng: random.Random, step: int) -> None:
    """One random thing a person might do on this device; refused ones are
    simply not done, as for a person."""
    choice = rng.choice(
        [
            "add",
            "add_child",
            "edit",
            "edit",
            "delete_record",
            "restore_record",
            "move_record",
            "delete_schema",
            "restore_schema",
            "delete_collection",
            "restore_collection",
            "unique",
            "rename_field",
            "add_field",
            "delete_field",
            "template",
        ]
    )
    try:
        if choice == "add":
            ctx.record_svc.add(
                "study",
                "encounter",
                {"site": rng.choice(["a", "b", "c"]), "depth": 2.0},
            )
        elif choice == "add_child" and (parents := _live_records(ctx, "encounter")):
            ctx.record_svc.add(
                "study",
                "sample",
                {"label": f"x{step}"},
                parent_record_id=rng.choice(parents)["id"],
            )
        elif choice == "edit":
            schema = rng.choice(["encounter", "sample", "note"])
            if records := _live_records(ctx, schema):
                record = ctx.record_svc.get(rng.choice(records)["id"])
                data = dict(record.data)
                names = [n for n in _field_names(ctx, schema) if n in data] or list(
                    data
                )
                if names:
                    name = rng.choice(names)
                    data[name] = (
                        float(step)
                        if isinstance(data[name], float)
                        else rng.choice(["a", "b", f"e{step}"])
                    )
                    ctx.record_svc.update(str(record.id), data)
        elif choice == "delete_record":
            schema = rng.choice(["encounter", "sample", "note"])
            if records := _live_records(ctx, schema):
                ctx.record_svc.delete(rng.choice(records)["id"])
        elif choice == "restore_record" and (gone := _deleted(ctx, "record")):
            ctx.record_svc.restore(rng.choice(gone)["id"])
        elif choice == "move_record":
            # An encounter (with its samples) or a note to the other collection.
            schema = rng.choice(["encounter", "note"])
            if records := _live_records(ctx, schema):
                picked = ctx.record_svc.get(rng.choice(records)["id"])
                here = ctx.dataset_svc.get_by_id(picked.dataset_id).name
                ctx.record_svc.move(
                    "extra" if here == "study" else "study", ids=[str(picked.id)]
                )
        elif choice == "delete_schema":
            ctx.schema_svc.delete(rng.choice(["sample", "note"]))
        elif choice == "restore_schema" and (gone := _deleted(ctx, "schema")):
            ctx.schema_svc.restore(rng.choice(gone)["name"])
        elif choice == "delete_collection":
            ctx.dataset_svc.delete("extra")
        elif choice == "restore_collection" and (gone := _deleted(ctx, "dataset")):
            ctx.dataset_svc.restore(rng.choice(gone)["name"])
        elif choice == "unique":
            ctx.schema_svc.set_unique_keys("encounter", rng.choice([[], [["site"]]]))
        elif choice == "rename_field":
            schema = rng.choice(["encounter", "sample", "note"])
            if names := _field_names(ctx, schema):
                old = rng.choice(names)
                ctx.schema_svc.update_field(
                    schema, old, new_name=f"{old.rstrip('0123456789')}{step}"
                )
        elif choice == "add_field":
            schema = rng.choice(["encounter", "note"])
            ctx.schema_svc.add_field(schema, rng.choice(["extra", "more"]), "string")
        elif choice == "delete_field":
            schema = rng.choice(["encounter", "sample", "note"])
            if names := _field_names(ctx, schema):
                ctx.schema_svc.delete_field(schema, rng.choice(names))
        elif choice == "template":
            schema = rng.choice(["encounter", "note"])
            if names := _field_names(ctx, schema):
                picked = rng.sample(names, k=min(2, len(names)))
                ctx.schema_svc.update(
                    schema, display_template=" ".join(f"{{{n}}}" for n in picked)
                )
        ctx.commit()
    except CivexError:
        ctx._session.rollback()


def broken_rules(ctx) -> list[str]:
    """Every rule a single machine holds a project to, checked on its state."""
    snap = snapshots(ctx)
    schemas = {s["id"]: s for s in snap["schema"]}
    datasets = {d["id"]: d for d in snap["dataset"]}
    records = {r["id"]: r for r in snap["record"]}
    live_fields: dict[str, dict[str, str]] = defaultdict(dict)  # schema -> id -> name
    for f in snap["field"]:
        if not f["deleted_at"]:
            live_fields[f["schema_id"]][f["id"]] = f["name"]

    def fields_of(schema_id: str | None) -> dict[str, str]:
        out: dict[str, str] = {}
        while schema_id and schema_id in schemas:
            out |= live_fields[schema_id]
            schema_id = schemas[schema_id].get("parent_id")
        return out

    problems: list[str] = []
    for r in records.values():
        if r["deleted_at"]:
            continue
        what = f"live record {r['id'][:8]}"
        schema, dataset = schemas.get(r["schema_id"]), datasets.get(r["dataset_id"])
        if schema is None or schema["deleted_at"]:
            problems.append(f"{what}: its schema is deleted")
        if dataset is None or dataset["deleted_at"]:
            problems.append(f"{what}: its collection is deleted")
        parent = records.get(r["parent_record_id"]) if r["parent_record_id"] else None
        if r["parent_record_id"] and (parent is None or parent["deleted_at"]):
            problems.append(f"{what}: its parent record is deleted")
        if parent is not None and parent["dataset_id"] != r["dataset_id"]:
            problems.append(f"{what}: it is in another collection than its parent")

    for s in schemas.values():
        if s["deleted_at"]:
            continue
        own = live_fields[s["id"]]
        for key in s.get("unique_keys") or []:
            if any(fid not in own for fid in key):
                problems.append(
                    f"schema {s['name']}: a unique key names a field it lacks"
                )
                continue
            seen: dict[tuple, str] = {}
            for r in records.values():
                if r["deleted_at"] or r["schema_id"] != s["id"]:
                    continue
                values = tuple((r["data"] or {}).get(fid) for fid in key)
                if any(v in (None, "") for v in values):
                    continue
                at = (r["dataset_id"], r["parent_record_id"], values)
                if at in seen:
                    problems.append(
                        f"schema {s['name']}: records {seen[at][:8]} and "
                        f"{r['id'][:8]} share a unique key"
                    )
                seen[at] = r["id"]
        if s.get("display_template"):
            names = set(fields_of(s["id"]).values()) | {"schema", "id"}
            missing = [
                n for n in referenced_names(s["display_template"]) if n not in names
            ]
            if missing:
                problems.append(
                    f"schema {s['name']}: its record name uses {missing}, which it lacks"
                )
    return problems


def scenario(project, authority, seed, steps: int = 40) -> list[str]:
    """Run the whole scenario against `authority` and return every rule broken
    on it and every unexplained difference on a device, in plain words."""
    rng = random.Random(f"invariants-{seed}")
    first = device(project, authority, "d1", flaky=True)
    populate(first)
    connect(first)
    devices = [first]
    for name in ("d2", "d3"):
        other = device(project, authority, name, flaky=True)
        connect(other)
        devices.append(other)
    quiesce(devices)

    for step in range(steps):
        act(rng.choice(devices), rng, step)
        if rng.random() < 0.35:
            who = rng.choice(devices)
            if rng.random() < 0.3:
                flaky(who).fail(
                    rng.choice(["push", "feed", "hello"]),
                    rng.choice(["refuse", "lose_reply"]),
                )
            try:
                who.sync_svc.sync()
            except SyncError:
                pass

    quiesce(devices)

    problems = [f"authority: {p}" for p in broken_rules(authority)]
    expected = snapshots(authority)
    for ctx in devices:
        name = ctx.config.project_root.name
        # A change the authority refused stays on the device that made it until
        # a person settles it: that difference is the point, not a fault.
        waiting = {str(c.entity_id)[:8] for c in ctx.sync_svc.conflicts()}
        problems += [
            f"{name} differs: {d}"
            for d in differences(expected, snapshots(ctx))
            if d.split()[1].rstrip(":") not in waiting
        ]
    return problems
