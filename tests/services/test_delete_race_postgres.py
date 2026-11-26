"""`test_delete_race` on PostgreSQL (the second UPDATE waits on the row lock and
re-checks `deleted_at IS NULL`), plus two real threads deleting at once."""

from __future__ import annotations

from .test_record_summary_postgres import ctx, pytestmark  # noqa: F401
from .test_delete_race import *  # noqa: F401,F403
from .test_delete_race import two  # noqa: F401

import threading  # noqa: E402
import uuid  # noqa: E402

from civex.domain.dtos import RecordChangesDTO  # noqa: E402


def test_two_deletes_of_the_same_records_write_one_entry_each(two):  # noqa: F811
    """Two real transactions through the service: the second plans on the
    records as live, waits on the first's row locks, and finds them deleted."""
    from .test_delete_race import _entries, _make

    first, second = two
    ids = _make(first, 5)
    wanted = [uuid.UUID(i) for i in ids]
    got: dict = {}
    first_done = first.record_svc.apply_changes(RecordChangesDTO(delete=wanted))

    def other():
        got["done"] = second.record_svc.apply_changes(RecordChangesDTO(delete=wanted))
        second.commit()

    t = threading.Thread(target=other)
    t.start()
    t.join(timeout=1.0)
    assert t.is_alive()  # blocked on the first writer's row locks
    first.commit()
    t.join(timeout=10)
    assert not t.is_alive()
    assert first_done.deleted == 5
    assert got["done"].deleted == 0
    assert all(_entries(first, "delete", i) == 1 for i in ids)
