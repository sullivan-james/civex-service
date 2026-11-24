"""The bulk restore tests of `test_restore_bulk`, on PostgreSQL (the update,
the history writer and the planner's chunked reads against the real thing).

Runs only when CIVEX_TEST_POSTGRES_URL names a server it may create databases
on (a throwaway one); the database is made by the summary tests' fixture."""

from __future__ import annotations

from .test_record_summary_postgres import ctx, pytestmark  # noqa: F401
from .test_restore_bulk import *  # noqa: F401,F403
from .test_restore_bulk import world  # noqa: F401


import os  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

from .test_restore_bulk import _count, _delete_event, leaf, seed  # noqa: E402
from civex.db.models import Record  # noqa: E402


@pytest.mark.skipif(
    not os.environ.get("CIVEX_BIG_ROUNDTRIP"),
    reason="set CIVEX_BIG_ROUNDTRIP=<records> (e.g. 70000) to time the round trip",
)
def test_a_big_delete_undo_redo_round_trip_with_timings(world):  # noqa: F811
    ctx = world  # noqa: F811
    total = int(os.environ["CIVEX_BIG_ROUNDTRIP"])
    seed(ctx, "c", total // 4, 3)
    everything = (total // 4) * 4

    def timed(label, work):
        started = time.monotonic()
        out = work()
        ctx.commit()
        print(f"\n{label}: {time.monotonic() - started:.1f}s")
        return out

    timed("delete", lambda: ctx.record_svc.delete_all("c"))
    batch = _delete_event(ctx).batch.id
    timed("undo preview", lambda: ctx.history_svc.revert_batch(batch))
    undone = timed("undo", lambda: ctx.history_svc.revert_batch(batch, dry_run=False))
    assert (undone.applied, undone.left) == (everything, 0)
    assert _count(ctx, Record.deleted_at.is_(None)) == everything
    events, _ = ctx.history_svc.events(where={"and": [leaf("how", "restore")]})
    redone = timed(
        "redo", lambda: ctx.history_svc.revert_batch(events[0].batch.id, dry_run=False)
    )
    assert (redone.applied, redone.left) == (everything, 0)
    assert _count(ctx, Record.deleted_at.is_(None)) == 0
