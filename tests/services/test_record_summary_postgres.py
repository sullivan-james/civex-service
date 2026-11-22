"""The summary tests of `test_record_summary`, on PostgreSQL: the same
answers from `jsonb_typeof`, `AT TIME ZONE` and `jsonb_array_elements` as
SQLite gives from `json_type`, a CASE over the zone's offsets and `json_each`.

Runs only when CIVEX_TEST_POSTGRES_URL names a server it may create
databases on (a throwaway one); each test makes a database of its own."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from civex.config import load_config
from civex.context import build_local_context
from civex.project import scaffold_project

from .test_record_summary import *  # noqa: F401,F403

_SERVER = os.environ.get("CIVEX_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not _SERVER, reason="CIVEX_TEST_POSTGRES_URL not set")


@pytest.fixture()
def ctx(tmp_path):
    assert _SERVER
    name = f"civex_{uuid.uuid4().hex[:12]}"
    admin = create_engine(_SERVER, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = _SERVER.rsplit("/", 1)[0] + f"/{name}"
    root = tmp_path / "project"
    scaffold_project(root, db_url=url)
    previous = os.getcwd()
    os.chdir(root)
    try:
        context = build_local_context(load_config())
    finally:
        os.chdir(previous)
    yield context
    context.close()
    context._session.get_bind().dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()
