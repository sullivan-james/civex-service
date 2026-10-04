"""A schema's display_fields list becomes the template joining those fields,
so every record keeps its name; downgrade reads the field names back."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

PREVIOUS = "c5e1a8d37b42"
HEAD_UNDER_TEST = "c4a9e17d5b20"


def _config() -> Config:
    migrations_dir = Path(__file__).resolve().parents[2] / "src/civex/db/migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    return cfg


def test_display_fields_become_a_template_and_back(tmp_path) -> None:
    cfg = _config()
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.connect() as c:
        cfg.attributes["connection"] = c
        command.upgrade(cfg, PREVIOUS)
        c.commit()

    now = datetime.now(timezone.utc)
    with_fields, without = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as c:
        for sid, name, fields in (
            (with_fields, "a", ["first", "last"]),
            (without, "b", []),
        ):
            c.execute(
                text(
                    "INSERT INTO schemas (id, name, display_fields, created_at) "
                    "VALUES (:id, :name, :df, :created_at)"
                ),
                {
                    "id": sid.hex,
                    "name": name,
                    "df": json.dumps(fields),
                    "created_at": now,
                },
            )

    with engine.connect() as c:
        cfg.attributes["connection"] = c
        command.upgrade(cfg, HEAD_UNDER_TEST)
        c.commit()
    with engine.connect() as c:
        rows = dict(c.execute(text("SELECT name, display_template FROM schemas")).all())
    assert rows == {"a": "{first} {last}", "b": None}

    with engine.connect() as c:
        cfg.attributes["connection"] = c
        command.downgrade(cfg, PREVIOUS)
        c.commit()
    with engine.connect() as c:
        back = dict(c.execute(text("SELECT name, display_fields FROM schemas")).all())
    assert {k: json.loads(v) for k, v in back.items()} == {
        "a": ["first", "last"],
        "b": [],
    }
