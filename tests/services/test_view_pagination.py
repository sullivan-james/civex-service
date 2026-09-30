"""View preview/export page through SQL (sort + limit/offset) instead of
fetching a capped window and sorting in Python."""

from __future__ import annotations

import io
import json

from civex.context import AppContext
from civex.services import view_service
from civex.services.view_service import write_csv, write_json


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
    assert seen[len(present):] == [None] * 5  # nulls last, even descending


def test_export_stream_walks_every_page(
    ctx, make_schema, make_collection, monkeypatch
) -> None:
    _seed(ctx, make_schema, make_collection)
    monkeypatch.setattr(view_service, "EXPORT_PAGE_SIZE", 4)
    ctx.view_svc.create(
        "trial",
        "all",
        columns=["subject"],
        sort=[{"field": "subject", "direction": "asc"}],
    )
    ctx.commit()

    batches = list(ctx.view_svc.export_stream("trial", "all").batches)
    assert len(batches) == 7  # 25 rows / 4 per page
    subjects = [r["subject"] for b in batches for r in b.rows]
    assert subjects == [f"S{i:02d}" for i in range(25)]  # no dupes, no gaps


def test_streaming_json_matches_materialised_json() -> None:
    rows = [{"a": 1, "c.d": "x"}, {"a": 2, "c.d": None}, {"a": 3, "c.d": "z"}]
    for chunks in ([rows], [rows[:1], rows[1:]], [rows[:2], [], rows[2:]]):
        out = io.StringIO()
        write_json(out, iter(chunks))
        assert out.getvalue() == view_service.rows_to_json(rows)
    out = io.StringIO()
    write_json(out, iter([]))
    assert json.loads(out.getvalue()) == []


def test_streaming_csv_matches_materialised_csv() -> None:
    rows = [{"a": 1, "b": [1, 2]}, {"a": 2, "b": None}]
    out = io.StringIO()
    write_csv(out, ["a", "b"], iter([rows[:1], rows[1:]]))
    assert out.getvalue() == view_service.rows_to_csv(["a", "b"], rows)
