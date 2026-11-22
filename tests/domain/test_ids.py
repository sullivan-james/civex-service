"""Time-ordered ids: valid, rising, with a short-id prefix that stays distinct,
and used for the busy tables."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from unittest import mock

import pytest

from civex.db.models import AuditLog, FileReference, Record, Schema
from civex.domain import ids
from civex.domain.ids import id_time, row_id, uuid7


@pytest.fixture(autouse=True)
def _fresh_generators(monkeypatch: pytest.MonkeyPatch) -> None:
    """The generators never go backwards, so a test that jumps the clock ahead
    would leave every later one behind it."""
    monkeypatch.setattr(ids, "_last_ms", -1)
    monkeypatch.setattr(ids, "_counter", 0)
    monkeypatch.setattr(ids, "_last_us", -1)
    monkeypatch.setattr(ids, "_us_counter", 0)


def test_uuid7_version_and_variant_are_rfc_9562() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_is_strictly_increasing_even_within_one_millisecond() -> None:
    made = [uuid7() for _ in range(20000)]
    assert made == sorted(made)
    assert len(set(made)) == len(made)


def test_uuid7_does_not_go_backwards_when_the_clock_does() -> None:
    first = uuid7()
    with mock.patch.object(ids.time, "time_ns", return_value=1_000_000):
        later = uuid7()
    assert later > first


def test_uuid7_counter_overflow_advances_the_timestamp_not_wraps() -> None:
    frozen = time.time_ns() + 10_000_000_000  # a fixed ms well ahead of earlier ids
    with mock.patch.object(ids.time, "time_ns", return_value=frozen):
        made = [uuid7() for _ in range(10000)]  # > 4096 per ms
    assert made == sorted(made)
    assert len(set(made)) == len(made)


def test_uuid7_creation_time_is_readable_from_the_id() -> None:
    before = datetime.now(timezone.utc)
    stamp = id_time(uuid7())
    after = datetime.now(timezone.utc)
    assert stamp is not None
    assert before.replace(microsecond=0) <= stamp <= after
    assert id_time(uuid.uuid4()) is None
    assert id_time(row_id()) is None


def test_row_id_is_a_valid_version_8_uuid() -> None:
    value = row_id()
    assert value.version == 8
    assert value.variant == uuid.RFC_4122


def test_row_ids_rise_with_time_within_a_lap() -> None:
    # Pin the clock inside a lap (not within 100 000 us of the 2**32 wrap).
    start = (1_800_000_000 * 1_000_000 // (1 << 32)) * (1 << 32) + 1_000_000
    with mock.patch.object(ids.time, "time_ns", return_value=start * 1000):
        made = [row_id() for _ in range(70000)]  # more than 2**16 in one microsecond
    assert made == sorted(made)
    assert len(set(made)) == len(made)
    ticks = iter(range(start, start + 5000))
    with mock.patch.object(ids.time, "time_ns", side_effect=lambda: next(ticks) * 1000):
        spread = [row_id() for _ in range(5000)]
    assert spread == sorted(spread)


def test_row_ids_do_not_go_backwards_when_the_clock_does() -> None:
    start = (1_800_000_000 * 1_000_000 // (1 << 32)) * (1 << 32) + 1_000_000
    with mock.patch.object(ids.time, "time_ns", return_value=start * 1000):
        first = row_id()
    with mock.patch.object(ids.time, "time_ns", return_value=(start - 5000) * 1000):
        later = row_id()
    assert later > first


def test_row_id_wraps_once_per_lap_and_the_prefix_stays_distinct() -> None:
    lap = 1 << 32
    base = (1_800_000_000 * 1_000_000 // lap + 1) * lap
    with mock.patch.object(ids.time, "time_ns", return_value=(base - 1) * 1000):
        before = row_id()
    with mock.patch.object(ids.time, "time_ns", return_value=(base + 1) * 1000):
        after = row_id()
    assert before.int >> 96 == lap - 1
    assert after.int >> 96 == 1
    # The first 8 hex characters (the short id) vary with the microsecond:
    # rows created 5 ms apart never share one.
    shorts = set()
    clock = iter(range(base + 10_000, base + 10_000 + 200 * 5_000, 5_000))
    with mock.patch.object(ids.time, "time_ns", side_effect=lambda: next(clock) * 1000):
        for _ in range(200):
            shorts.add(str(row_id())[:8])
    assert len(shorts) == 200


def test_the_busy_tables_take_time_ordered_ids_and_the_rest_stay_v4() -> None:
    for model in (Record, AuditLog, FileReference):
        assert model.id.default.arg(None).version == 8
    assert Schema.id.default.arg(None).version == 4
