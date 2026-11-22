"""A kind's charts and the Analytics page travel between devices (scenarios).

A kind's charts are part of its schema, and the Analytics page is one synced
thing (`dashboard`) holding its cards, each chart with the records it counts.
`travels` sets a kind's charts and edits the page on one device, edits it
again on another, and checks every copy ends with the same charts and page;
`two_first_edits` has two devices edit a page nobody had edited, which both
make as the same thing (`DASHBOARD_ID`), and checks the authority's stays with
the other kept for review. Each returns what is wrong (nothing is a pass), so
a host embedding civex can run them with its own app as the authority."""

from __future__ import annotations

from civex.domain.dashboard import DASHBOARD_ID

from civex.testing.peers import build_study, connect, device


def _page(ctx) -> list[dict] | None:
    snap = ctx.sync_repo.snapshot("dashboard", DASHBOARD_ID)
    return snap["cards"] if snap else None


def travels(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    charts = [{"id": "a", "group_by": ["site"], "measures": ["count", "mean:depth"]}]
    laptop.schema_svc.set_charts("encounter", charts)
    laptop.dashboard_svc.add(
        chart={"group_by": ["site"]},
        schema="encounter",
        collection="study",
        size="wide",
    )
    laptop.commit()
    connect(laptop)

    phone = device(project, authority, "phone")
    connect(phone)
    got = phone.schema_svc.get("encounter").charts
    if got != charts:
        problems.append(f"the phone's charts are {got}, not {charts}")
    if _page(phone) != _page(laptop):
        problems.append("the phone did not get the page as the laptop made it")

    # The phone takes a widget off; the laptop sees it go.
    first_widget = next(c for c in phone.dashboard_svc.cards() if c.widget)
    phone.dashboard_svc.remove(first_widget.id)
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    # ... and changes the kind's charts; the laptop gets those too.
    phone.schema_svc.set_charts("encounter", [])
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    for name, ctx in (("authority", authority), ("laptop", laptop)):
        if _page(ctx) != _page(phone):
            problems.append(f"the {name}'s page differs from the phone's")
        if ctx.schema_svc.get("encounter").charts:
            problems.append(f"the {name} kept charts the phone cleared")
    entries = authority.history_svc.page(limit=50, entity_type="dashboard")
    if len(entries) < 2:
        problems.append(f"the authority's history has {len(entries)} page edits")
    return problems


def two_first_edits(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    laptop.dashboard_svc.add(widget="storage", size="wide")
    laptop.commit()
    phone.dashboard_svc.remove("widget-storage")
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    if not (_page(authority) == _page(laptop) == _page(phone)):
        problems.append("the copies of the page differ")
    if _page(authority) != _page(laptop):
        problems.append("the first page to reach the authority did not stay")
    if not any(c.entity_type == "dashboard" for c in phone.sync_svc.conflicts()):
        problems.append("the phone's page was not kept for review")
    return problems
