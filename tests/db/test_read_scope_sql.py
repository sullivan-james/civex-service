"""The history rule is written so that no database plans it as a scan of the
records table (review of C3a, item 5): its SQL carries no `IN (SELECT ...)`.
The PostgreSQL plan itself is pinned in test_postgres_read_scope.py; this holds
on every database CI runs."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from civex.db import read_scope
from civex.db.models import AuditLog
from civex.domain.permissions import ReadScope


def _sql(dialect, scope: ReadScope) -> str:
    return str(
        select(AuditLog.id)
        .where(read_scope._entry_visible(scope))
        .compile(dialect=dialect(), compile_kwargs={"literal_binds": True})
    ).upper()


def test_the_history_rule_has_no_in_subquery_under_or():
    for scope in (
        ReadScope(only=frozenset({uuid.uuid4()})),
        ReadScope(hidden=frozenset({uuid.uuid4()})),
    ):
        for dialect in (sqlite.dialect, postgresql.dialect):
            sql = _sql(dialect, scope)
            assert "IN (SELECT" not in sql
            # each probe is correlated to the audit row, by key
            assert sql.count("(SELECT") >= 2
            assert "AUDIT_LOG.ENTITY_ID" in sql


def test_unknown_and_release_entries_are_not_in_the_rule():
    sql = _sql(sqlite.dialect, ReadScope(only=frozenset({uuid.uuid4()})))
    assert "'RELEASE'" not in sql
    for shared in ("'SCHEMA'", "'FIELD'", "'VIEW'", "'DASHBOARD'"):
        assert shared in sql
