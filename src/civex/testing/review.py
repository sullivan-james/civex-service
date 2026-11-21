"""Review status and notes travel between devices (scenarios).

`travels` marks a record and leaves a note on one device, and checks another
device and the authority get both, then resolves the note on the second device
and checks the first sees it. `marked_at_once` has two devices give one record
a different review status at the same time: the later one stays everywhere and
nothing is kept for review (a review is never a conflict, `merge.LATEST_WINS`).
Each returns what is wrong (nothing is a pass), so a host embedding civex can
run them with its own app as the authority."""

from __future__ import annotations

from civex.domain import review as review_rules

from civex.testing.peers import build_study, connect, device


def _status(ctx, record_id) -> str:
    return review_rules.status_of(ctx.record_svc.get(str(record_id)).review)


def _notes(ctx, record_id) -> list[tuple[str, bool]]:
    return [
        (n.body, n.resolved_at is not None) for n in ctx.note_svc.notes(str(record_id))
    ]


def travels(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)

    laptop.record_svc.set_review("needs_check", ids=[str(record.id)])
    note = laptop.note_svc.add(str(record.id), "depth looks off, re-check")
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    for name, ctx in (("authority", authority), ("phone", phone)):
        if _status(ctx, record.id) != "needs_check":
            problems.append(f"the {name}'s record is {_status(ctx, record.id)}")
        if _notes(ctx, record.id) != [("depth looks off, re-check", False)]:
            problems.append(f"the {name} has notes {_notes(ctx, record.id)}")

    phone.note_svc.resolve(str(note.id))
    phone.record_svc.set_review("checked", ids=[str(record.id)])
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    if _notes(laptop, record.id) != [("depth looks off, re-check", True)]:
        problems.append(f"the laptop has notes {_notes(laptop, record.id)}")
    if _status(laptop, record.id) != "checked":
        problems.append(f"the laptop's record is {_status(laptop, record.id)}")
    kinds = {
        e.entity_type for e in authority.history_svc.page(limit=50, entity_type="note")
    }
    if kinds != {"note"}:
        problems.append("the authority's history has no entries about the note")
    return problems


def marked_at_once(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    laptop.record_svc.set_review("checked", ids=[str(record.id)])
    laptop.commit()
    phone.record_svc.set_review("needs_check", ids=[str(record.id)])
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    statuses = {_status(c, record.id) for c in (authority, laptop, phone)}
    if statuses != {"needs_check"}:
        problems.append(f"the copies hold {statuses}, not the later 'needs_check'")
    for name, ctx in (("laptop", laptop), ("phone", phone)):
        if ctx.sync_svc.conflicts():
            problems.append(f"the {name} has a review kept for review")
    return problems
