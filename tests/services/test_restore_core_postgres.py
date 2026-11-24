"""The core's tests on PostgreSQL: the bulk history writer is COPY there, so
its rows, defaults and ordering are checked against the real thing (with
whichever driver CIVEX_TEST_POSTGRES_URL names: psycopg 2 or psycopg 3).

Runs only when CIVEX_TEST_POSTGRES_URL names a server it may create databases
on (a throwaway one)."""

from __future__ import annotations

from .test_record_summary_postgres import ctx, pytestmark  # noqa: F401
from .test_restore_core import (  # noqa: F401
    referenced,
    test_a_bulk_entry_equals_a_log_change_entry_column_by_column,
    test_a_refused_redo_is_refused_in_the_preview_too,
    test_force_reaches_the_redo_and_a_preview_writes_nothing,
)
