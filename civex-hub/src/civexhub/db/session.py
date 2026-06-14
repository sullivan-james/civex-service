from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civexhub.db.models import Base


@lru_cache(maxsize=1)
def get_engine(database_url: str) -> Engine:
    return create_engine(database_url)


def create_hub_tables(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS civexhub"))
        conn.commit()
    Base.metadata.create_all(engine)
    _apply_hub_migrations(engine)


def _apply_hub_migrations(engine: Engine) -> None:
    """Idempotent column/table additions for existing hub databases."""
    migrations = [
        "ALTER TABLE civexhub.repositories ADD COLUMN IF NOT EXISTS org_id UUID REFERENCES civexhub.organizations(id)",
        "ALTER TABLE civexhub.users ADD COLUMN IF NOT EXISTS display_name VARCHAR(255)",
        "ALTER TABLE civexhub.users ADD COLUMN IF NOT EXISTS bio VARCHAR(500)",
        "ALTER TABLE civexhub.users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(1000)",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                conn.rollback()


def create_repo_schema(engine: Engine, repo_id_hex: str) -> None:
    """Create a PostgreSQL schema for a repo and initialise civex tables in it."""
    from civex.db.models import Base as CivexBase
    schema_name = f"repo_{repo_id_hex}"
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        conn.commit()
    repo_engine = create_engine(
        engine.url.render_as_string(hide_password=False),
        connect_args={"options": f"-csearch_path={schema_name}"},
    )
    CivexBase.metadata.create_all(repo_engine)
    repo_engine.dispose()


def drop_repo_schema(engine: Engine, repo_id_hex: str) -> None:
    schema_name = f"repo_{repo_id_hex}"
    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
        conn.commit()


def get_session(engine: Engine) -> Session:
    return Session(engine)
