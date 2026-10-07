"""inventory: a file may be stored on several drives

`stored_objects` had one row per file (`sha256` the key), so the store could
only say one drive held it. A collection whose home is a drive now keeps a
copy of every file it uses there, even one another collection keeps on
another drive, so the inventory has a row per file per drive: the key becomes
(`sha256`, `volume`). Existing rows are kept as they are (each is one copy).

Revision ID: c3f7a9e1d5b8
Revises: b5e1d8f2a647
Create Date: 2026-10-07 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import civex.db.models

revision: str = "c3f7a9e1d5b8"
down_revision: Union[str, None] = "b5e1d8f2a647"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _primary_key(columns: list[str]) -> None:
    bind = op.get_bind()
    pk = sa.inspect(bind).get_pk_constraint("stored_objects")
    if list(pk["constrained_columns"]) == columns:
        return
    if bind.dialect.name == "postgresql":
        op.drop_constraint(pk["name"] or "stored_objects_pkey", "stored_objects")
        op.create_primary_key("stored_objects_pkey", "stored_objects", columns)
        return
    # SQLite can't change a primary key in place: a new table, then a swap.
    op.create_table(
        "_stored_objects_new",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("volume", sa.String(length=255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", civex.db.models._UTCDateTime(timezone=True), nullable=False
        ),
        sa.PrimaryKeyConstraint(*columns),
    )
    op.execute(
        "INSERT INTO _stored_objects_new (sha256, volume, size, created_at) "
        "SELECT sha256, volume, size, created_at FROM stored_objects"
    )
    op.drop_index("ix_stored_objects_volume", table_name="stored_objects")
    op.drop_table("stored_objects")
    op.rename_table("_stored_objects_new", "stored_objects")
    op.create_index("ix_stored_objects_volume", "stored_objects", ["volume"])


def upgrade() -> None:
    _primary_key(["sha256", "volume"])


def downgrade() -> None:
    # Keep one copy of each file: the first drive's, by name.
    op.execute(
        "DELETE FROM stored_objects WHERE EXISTS (SELECT 1 FROM stored_objects o "
        "WHERE o.sha256 = stored_objects.sha256 AND o.volume < stored_objects.volume)"
    )
    _primary_key(["sha256"])
