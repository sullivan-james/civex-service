from __future__ import annotations

from contextlib import contextmanager
from functools import cache
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civex.config import load_config
from civex.db.engine import enable_sqlite_foreign_keys


@cache
def _engine() -> Engine:
    """One engine per process — cached after first call."""
    config = load_config()
    return enable_sqlite_foreign_keys(create_engine(config.db.url))


@contextmanager
def get_session() -> Generator[Session, None, None]:
    with Session(_engine()) as session:
        yield session
