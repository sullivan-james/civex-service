"""Notes and their threads travel between devices (scenarios).

`travels` leaves a note on one device and checks another device and the
authority get it, replies and resolves the thread on the second device and
checks the first sees both. `replies_at_once` has two devices reply in one
thread at the same time: both replies arrive everywhere, in one thread, and
nothing is kept for review (they are two notes, not two values of one).
Each returns what is wrong (nothing is a pass), so a host embedding civex can
run them with its own app as the authority."""

from __future__ import annotations

from civex.testing.peers import build_study, connect, device


def _threads(ctx, record_id) -> list[tuple[str, bool, list[str]]]:
    return [
        (t.body, t.resolved_at is not None, sorted(r.body for r in t.replies))
        for t in ctx.note_svc.notes(str(record_id))
    ]


def travels(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)

    note = laptop.note_svc.add(str(record.id), "depth looks off, re-check")
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    for name, ctx in (("authority", authority), ("phone", phone)):
        if _threads(ctx, record.id) != [("depth looks off, re-check", False, [])]:
            problems.append(f"the {name} has notes {_threads(ctx, record.id)}")

    phone.note_svc.reply(str(note.id), "it was the sensor")
    phone.note_svc.resolve(str(note.id))
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    want = [("depth looks off, re-check", True, ["it was the sensor"])]
    if _threads(laptop, record.id) != want:
        problems.append(f"the laptop has notes {_threads(laptop, record.id)}")
    kinds = {
        e.entity_type for e in authority.history_svc.page(limit=50, entity_type="note")
    }
    if kinds != {"note"}:
        problems.append("the authority's history has no entries about the note")
    return problems


def replies_at_once(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    note = laptop.note_svc.add(str(record.id), "which sensor was this?")
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    laptop.note_svc.reply(str(note.id), "the old one")
    laptop.commit()
    phone.note_svc.reply(str(note.id), "the new one")
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    want = [("which sensor was this?", False, ["the new one", "the old one"])]
    for name, ctx in (("authority", authority), ("laptop", laptop), ("phone", phone)):
        if _threads(ctx, record.id) != want:
            problems.append(f"the {name} has {_threads(ctx, record.id)}")
    for name, ctx in (("laptop", laptop), ("phone", phone)):
        if ctx.sync_svc.conflicts():
            problems.append(f"the {name} has a reply kept for review")
    return problems
