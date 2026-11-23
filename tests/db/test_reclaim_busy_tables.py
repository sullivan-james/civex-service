"""A table another session holds a lock on is skipped and named; the rest go on.
Any other failure (a full disk, a lost connection) is not mistaken for a busy table."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from civex.repositories.local import db_space
from civex.repositories.local.db_space import LocalDbSpace, TableSpace


class _Orig(Exception):
    def __init__(self, code: str) -> None:
        self.pgcode = code


class _Conn:
    def __init__(self, fail: dict[str, str]) -> None:
        self.fail, self.ran = fail, []

    def execution_options(self, **_):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def exec_driver_sql(self, sql: str):
        self.ran.append(sql)
        for name, code in self.fail.items():
            if f'"{name}"' in sql:
                raise OperationalError(sql, {}, _Orig(code))


def _svc(monkeypatch, fail):
    conn = _Conn(fail)
    engine = SimpleNamespace(
        dialect=SimpleNamespace(
            name="postgresql",
            identifier_preparer=SimpleNamespace(quote=lambda n: f'"{n}"'),
        ),
        connect=lambda: conn,
    )
    svc = LocalDbSpace(engine)
    tables = [
        TableSpace("big", 10**9, 9 * 10**8, "s"),
        TableSpace("small", 10**8, 9 * 10**7, "s"),
    ]
    monkeypatch.setattr(svc, "_postgres_tables", lambda: tables)
    return svc, conn


def test_a_lock_timeout_skips_that_table_only(monkeypatch):
    svc, conn = _svc(monkeypatch, {"big": "55P03"})
    assert svc.reclaim() == ["big"]
    assert any('"small"' in q for q in conn.ran)


def test_another_failure_is_not_a_busy_table(monkeypatch):
    svc, _ = _svc(monkeypatch, {"big": "53100"})  # disk full
    with pytest.raises(OperationalError):
        svc.reclaim()


def test_the_worth_thresholds_are_unchanged():
    assert db_space.WORTH_BYTES > db_space.MIN_BYTES
