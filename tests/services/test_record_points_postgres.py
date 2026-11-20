"""The map points tests of `test_record_points`, on PostgreSQL: geometries
read through `jsonb_typeof` as SQLite reads them through `json_type`.

Runs only when CIVEX_TEST_POSTGRES_URL names a server it may create
databases on (a throwaway one); the database is made by the summary tests'
fixture."""

from __future__ import annotations

from .test_record_points import *  # noqa: F401,F403
from .test_record_summary_postgres import ctx, pytestmark  # noqa: F401
