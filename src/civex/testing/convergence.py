"""Devices end up agreeing whatever the order (the convergence scenario).

Three devices edit, add, delete, restore and rename at random and sync at random
through a network that drops replies; afterwards every copy must equal the
authority. `scenario` returns what differs (nothing is a pass); a failing seed
replays it."""

from __future__ import annotations

import random

from civex.domain.exceptions import CivexError
from civex.domain.sync import SyncError

from civex.testing.peers import connect, device, flaky, snapshots


def populate(ctx):
    ctx.schema_svc.create("encounter")
    ctx.schema_svc.add_field("encounter", "site", "string")
    ctx.schema_svc.add_field("encounter", "depth", "float")
    ctx.dataset_svc.create("study")
    for n in range(4):
        ctx.record_svc.add("study", "encounter", {"site": f"s{n}", "depth": float(n)})
    ctx.commit()


def live(ctx):
    return ctx.record_svc.find("study", "encounter", limit=500)


def deleted(ctx):
    return [
        r
        for r in ctx.sync_repo.snapshots_page("record", None, 500)
        if r["deleted_at"] is not None
    ]


def act(ctx, rng: random.Random, step: int) -> None:
    """One random thing a person might do on this device."""
    choice = rng.choice(["edit", "edit", "edit", "add", "delete", "restore", "rename"])
    try:
        if choice == "edit" and (records := live(ctx)):
            record = rng.choice(records)
            data = dict(record.data)
            field = rng.choice([k for k in data if k in ("site", "depth")] or ["site"])
            data[field] = f"v{step}" if field == "site" else float(step)
            ctx.record_svc.update(str(record.id), data)
        elif choice == "add":
            ctx.record_svc.add("study", "encounter", {"site": f"n{step}", "depth": 0.5})
        elif choice == "delete" and (records := live(ctx)):
            ctx.record_svc.delete(str(rng.choice(records).id))
        elif choice == "restore" and (gone := deleted(ctx)):
            ctx.record_svc.restore(str(rng.choice(gone)["id"]))
        elif choice == "rename":
            names = [f.name for f in ctx.schema_svc.get("encounter").fields]
            old = rng.choice(names)
            ctx.schema_svc.update_field(
                "encounter", old, new_name=f"{old.rstrip('0123456789')}{step}"
            )
        ctx.commit()
    except CivexError:
        ctx._session.rollback()  # a thing a person couldn't do right now


def differences(expected: dict, actual: dict) -> list[str]:
    """What differs between two projects, thing by thing and value by value."""
    out: list[str] = []
    for kind in expected:
        want = {x["id"]: x for x in expected[kind]}
        have = {x["id"]: x for x in actual[kind]}
        for missing in sorted(set(want) - set(have)):
            out.append(f"{kind} {missing[:8]} is missing")
        for extra in sorted(set(have) - set(want)):
            out.append(f"{kind} {extra[:8]} should not exist")
        for key in sorted(set(want) & set(have)):
            if want[key] != have[key]:
                keys = [k for k in want[key] if want[key][k] != have[key].get(k)]
                out.append(
                    f"{kind} {key[:8]}: "
                    + "; ".join(
                        f"{k}: authority={want[key][k]!r} device={have[key].get(k)!r}"
                        for k in keys
                    )
                )
    return out


def quiesce(devices) -> None:
    for ctx in devices:
        flaky(ctx).clear()  # the network behaves from here
    for _ in range(4):
        moved = False
        for ctx in devices:
            report = ctx.sync_svc.sync()
            moved = moved or report.changed or report.conflicts > 0
        if not moved:
            return
    raise AssertionError("devices were still exchanging changes after four rounds")


def scenario(project, authority, seed, steps: int = 40) -> list[str]:
    """Run the whole scenario against `authority` (any `AppContext`: a project
    in a folder, or one a host built its own way) and return every way a
    device's copy differs from it afterwards."""
    rng = random.Random(seed)
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
        ctx = rng.choice(devices)
        act(ctx, rng, step)
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
                pass  # the network dropped it; it will be retried

    quiesce(devices)

    expected = snapshots(authority)
    problems: list[str] = []
    for ctx in devices:
        name = ctx.sync_svc._config.project_root.name
        problems += [
            f"{name} differs from the authority: {d}"
            for d in differences(expected, snapshots(ctx))
        ]
    return problems
