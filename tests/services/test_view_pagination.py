"""View preview/export page through SQL (sort + limit/offset) instead of
fetching a capped window and sorting in Python."""

from __future__ import annotations

from civex.context import AppContext
from civex.services import file_access_service


def _seed(ctx: AppContext, make_schema, make_collection, n: int = 25) -> None:
    make_schema("trial", fields=[("subject", "string"), ("score", "integer")])
    make_collection("study")
    for i in range(n):
        # score 100..124 inserted in scrambled order; every 5th has none
        data = {"subject": f"S{i:02d}"}
        if i % 5:
            data["score"] = (i * 7) % n + 100
        ctx.record_svc.add("study", "trial", data)
    ctx.commit()


def test_preview_sorts_and_pages_in_sql(ctx, make_schema, make_collection) -> None:
    _seed(ctx, make_schema, make_collection)
    sort = [{"field": "score", "direction": "desc"}]
    seen: list = []
    for offset in (0, 10, 20):
        rows, total = ctx.view_svc.preview(
            "trial", columns=["subject", "score"], sort=sort, limit=10, offset=offset
        )
        assert total == 25
        seen.extend(r["score"] for r in rows)

    assert len(seen) == 25
    present = [s for s in seen if s is not None]
    assert present == sorted(present, reverse=True)  # numeric, not lexical
    assert seen[len(present) :] == [None] * 5  # nulls last, even descending


def test_table_export_walks_every_page(
    ctx, make_schema, make_collection, monkeypatch
) -> None:
    _seed(ctx, make_schema, make_collection)
    monkeypatch.setattr(file_access_service, "TABLE_PAGE", 4)
    ctx.view_svc.create(
        "trial",
        "all",
        columns=["subject"],
        sort=[{"field": "subject", "direction": "asc"}],
    )
    ctx.commit()

    selection = ctx.view_svc.table_selection("trial", "all")
    plan = ctx.file_access_svc.plan(selection)
    (table,) = plan.tables
    batches = list(ctx.file_access_svc.table_rows(selection, plan, table))
    assert len(batches) == 7  # 25 rows / 4 per page
    subjects = [r["subject"] for b in batches for r in b]
    assert subjects == [f"S{i:02d}" for i in range(25)]  # no dupes, no gaps
