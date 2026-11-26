"""`test_delete_race` on PostgreSQL (the second UPDATE waits on the row lock and
re-checks `deleted_at IS NULL`), plus two real threads deleting at once."""

from __future__ import annotations

from .test_record_summary_postgres import ctx, pytestmark  # noqa: F401
from .test_delete_race import *  # noqa: F401,F403
from .test_delete_race import two  # noqa: F401

import threading  # noqa: E402
import uuid  # noqa: E402


def test_a_delete_that_waits_on_the_others_lock_deletes_nothing(two):  # noqa: F811
    from .test_delete_race import _entries, _make

    first, second = two
    ids = _make(first, 5)
    wanted = [uuid.UUID(i) for i in ids]
    got: dict = {}
    first_won = first.record_svc._records.delete_many(wanted)  # rows locked, uncommitted

    def other():
        got["won"] = second.record_svc._records.delete_many(wanted)  # waits for the lock
        second.commit()

    t = threading.Thread(target=other)
    t.start()
    t.join(timeout=0.5)
    assert t.is_alive()  # blocked on the first writer's row locks
    first.commit()
    t.join(timeout=10)
    assert first_won == set(wanted) and got["won"] == set()
    assert all(_entries(first, "delete", i) == 0 for i in ids)
