"""The chunked delete, restore, purge and move of `test_chunked_tree_actions`
on PostgreSQL: the deferred parent key is checked at each commit there, so a
chunk that split a tree (or purged a parent before what sits under it) fails.

Runs only when CIVEX_TEST_POSTGRES_URL names a server it may create databases
on (a throwaway one); the database is made by the summary tests' fixture."""

from __future__ import annotations

from .test_chunked_tree_actions import *  # noqa: F401,F403
from .test_chunked_tree_actions import forest  # noqa: F401
from .test_record_summary_postgres import ctx, pytestmark  # noqa: F401
