"""sync_meta.readable: the collections a device was last told it may read

Revision ID: d9e3a5c7f1b4
Revises: e7a1c5d9b3f2
Create Date: 2026-11-22 20:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Mirrors models._JSON -- JSONB on PostgreSQL, plain JSON elsewhere.
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

revision: str = "d9e3a5c7f1b4"
down_revision: Union[str, None] = "e7a1c5d9b3f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sync_meta") as batch:
        batch.add_column(sa.Column("readable", _JSON, nullable=True))
        batch.add_column(
            sa.Column(
                "placed_from",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("history_scan", sa.BigInteger(), nullable=True))
    # What is stored now was stored before entries were stamped with where the
    # authority really had the record: the number of the last of them (an index
    # lookup, however long the history).
    op.execute(
        "UPDATE sync_meta SET placed_from = "
        "COALESCE((SELECT MAX(hub_seq) FROM audit_log), 0)"
    )


def downgrade() -> None:
    with op.batch_alter_table("sync_meta") as batch:
        batch.drop_column("history_scan")
        batch.drop_column("placed_from")
        batch.drop_column("readable")
