"""The bulk restore tests of `test_restore_bulk`, on PostgreSQL (the update,
the history writer and the planner's chunked reads against the real thing).

Runs only when CIVEX_TEST_POSTGRES_URL names a server it may create databases
on (a throwaway one); the database is made by the summary tests' fixture."""

from __future__ import annotations

from .test_record_summary_postgres import ctx, pytestmark  # noqa: F401
from .test_restore_bulk import *  # noqa: F401,F403
from .test_restore_bulk import world  # noqa: F401
