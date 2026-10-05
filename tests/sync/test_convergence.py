"""However devices interleave, they end up agreeing.

Three devices make random changes (edit, add, delete, restore, rename a field)
and sync at random moments, some of them through a network that drops replies.
Afterwards every device syncs until nothing moves and all of them, and the
authority, must hold exactly the same project. A failure prints the seed, which
replays it."""

from __future__ import annotations

import os
import random

import pytest

from civex.domain.exceptions import CivexError
from civex.domain.sync import SyncError

from .peers import connect, device, flaky, snapshots

# More seeds (and a different start) on demand: CIVEX_SYNC_SEEDS=300 pytest ...
SEEDS = range(
    int(os.environ.get("CIVEX_SYNC_FIRST_SEED", "0")),
    int(os.environ.get("CIVEX_SYNC_FIRST_SEED", "0"))
    + int(os.environ.get("CIVEX_SYNC_SEEDS", "25")),
)


def populate(ctx):
    ctx.schema_svc.create("encounter")
    ctx.schema_svc.add_field("encounter", "site", "string")
    ctx.schema_svc.add_field("encounter", "depth", "float")
    ctx.dataset_svc.create("study")
    ctx.dataset_svc.update("study", schemas=["encounter"])
    for n in range(4):
        ctx.record_svc.add("study", "encounter", {"site": f"s{n}", "depth": float(n)})
    ctx.commit()


def live(ctx):
    return ctx.record_svc.find("study", "encounter", limit=500)


def deleted(ctx):
    return [
        r
        for r in ctx.sync_repo.snapshots_page("record", 0, 500)
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


@pytest.mark.parametrize("seed", SEEDS)
def test_devices_end_up_agreeing_whatever_the_order(project, seed):
    rng = random.Random(seed)
    authority = project("authority")
    first = device(project, authority, "d1", flaky=True)
    populate(first)
    connect(first)
    devices = [first]
    for name in ("d2", "d3"):
        other = device(project, authority, name, flaky=True)
        connect(other)
        devices.append(other)
    quiesce(devices)

    for step in range(40):
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
    for ctx in devices:
        problems = differences(expected, snapshots(ctx))
        assert not problems, (
            f"seed {seed}: {ctx.sync_svc._config.project_root.name} differs from "
            "the authority:\n" + "\n".join(problems)
        )
