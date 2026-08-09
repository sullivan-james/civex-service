"""b3d71a04f6c2 adds schemas.label / fields.label.

The point of the migration is that it is *non-destructive*: rows that existed
before it keep their names and simply gain a NULL label, which every reader
treats as "derive one from the name". Nothing is backfilled and nothing that
predates slug validation is rewritten.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE_REVISION = "0291e474801b"  # head just before this migration
_POST_REVISION = "b3d71a04f6c2"  # this migration


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def test_existing_rows_gain_a_null_label_and_keep_their_names(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'labels.db'}")
    cfg = _config()

    schema_id = str(uuid.uuid4())
    field_id = str(uuid.uuid4())

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE_REVISION)
        conn.commit()

        # A name that slug validation would reject today — it must survive.
        conn.execute(
            text(
                "INSERT INTO schemas (id, name, created_at) "
                "VALUES (:id, 'Legacy Schema', '2024-01-01')"
            ),
            {"id": schema_id},
        )
        conn.execute(
            text(
                "INSERT INTO fields "
                "(id, schema_id, name, dtype, required, restrictions, created_at) "
                "VALUES (:id, :schema_id, 'Legacy Field', 'string', 0, '{}', "
                "'2024-01-01')"
            ),
            {"id": field_id, "schema_id": schema_id},
        )
        conn.commit()

        command.upgrade(cfg, _POST_REVISION)
        conn.commit()

        schema_row = conn.execute(
            text("SELECT name, label FROM schemas WHERE id = :id"), {"id": schema_id}
        ).fetchone()
        field_row = conn.execute(
            text("SELECT name, label FROM fields WHERE id = :id"), {"id": field_id}
        ).fetchone()

    assert schema_row == ("Legacy Schema", None)
    assert field_row == ("Legacy Field", None)


def test_downgrade_drops_both_columns(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'labels_down.db'}")
    cfg = _config()

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _POST_REVISION)
        conn.commit()

        inspector = inspect(conn)
        assert "label" in {c["name"] for c in inspector.get_columns("schemas")}
        assert "label" in {c["name"] for c in inspector.get_columns("fields")}

        command.downgrade(cfg, _PRE_REVISION)
        conn.commit()

        inspector = inspect(conn)
        assert "label" not in {c["name"] for c in inspector.get_columns("schemas")}
        assert "label" not in {c["name"] for c in inspector.get_columns("fields")}
